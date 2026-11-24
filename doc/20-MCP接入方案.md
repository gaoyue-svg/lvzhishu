# 必应中文搜索 MCP 接入方案

> 版本：v1.0 · 状态：设计草案 · 关联文档：[19-多Agent编排与治理方案](19-多Agent编排与治理方案.md)、[16-Agent设计方案](16-Agent设计方案.md)

## 0. 决策确认（已拍板）

- **服务器形态**：外部已有的 **Streamable HTTP** 必应搜索 MCP 服务器（客户端只连 URL，不自建）。
- **适配范围**：**仅必应搜索单工具**，不做通用 MCP 适配层。
- **鉴权**：必应 API Key 由 **MCP 服务器侧持有**，LawRAG 只调用工具，不做用户级 Key 管理。

## 1. 背景与目标

### 1.1 现状

- `case_analysis`（案例分析）联网检索类案走 `WebSearchTool`（`agent_service/tools/web_search.py`），当前是 **Tavily REST** 直连（httpx POST），非 SDK。
- `BaseTool` 抽象（`name/description/parameters_schema/execute`）与 `ToolRegistry.schemas()` 已预留 OpenAI/MCP 风格对齐，doc/16 明确"未来迁移 MCP 时只需把 BaseTool.execute 改为 HTTP/MCP 调用，Agent 侧代码不变"。
- 全仓**无任何 MCP 代码**（无 `mcp` 依赖、无客户端、无服务器）。
- `web_search.py` 已按 `settings.web_search_provider` 分发，`bing_mcp` 分支为占位降级（`available=false`）。

### 1.2 目标

1. LawRAG 后端作为 **MCP 客户端**，接入**必应中文搜索 MCP**，为案例分析提供中文类案联网检索，替代 Tavily。
2. 复用现有工具链路（`ToolRegistry` → `tool_exec_node` → `citation_node`），**业务 Agent 零改动**。
3. 保持 `WebSearchTool` 返回契约 `{available, results, citations, message}` 不变，前端与测试无缝沿用。
4. 失败降级：MCP 不可用返回 `available=false`，不阻塞 Agent。
5. 预留**通用 MCP 适配能力**（白名单约束），未来可接入更多 MCP 工具。

---

## 2. 角色与协议

| 角色 | 说明 |
|---|---|
| MCP **Server** | 必应搜索能力提供方。**外部已有 Streamable HTTP 服务器**（配置 URL 即可）。 |
| MCP **Client** | 本项目 LawRAG 后端。负责 `initialize` → `tools/list` → `tools/call`。 |
| 工具契约 | MCP 工具 `bing_web_search(query, max_results)` → 结构化搜索结果。 |

传输：**Streamable HTTP**（`bing_mcp_server_url`）。stdio 仅作未来扩展位，不实现。

---

## 3. 总体架构

```
case_analysis (Agent)
  └─ tool_decide_node → pending_tool_calls=[{name:"web_search", ...}]
       └─ ToolRegistry.execute("web_search", ...)
            └─ WebSearchTool.execute
                 └─ provider = settings.web_search_provider
                      ├─ tavily → httpx POST Tavily REST（现有，不动）
                      └─ bing_mcp → MCPClientManager.call_tool(bing_mcp_tool_name, {query, max_results})
                                     └─ MCP ClientSession（streamable http / stdio）
                                          └─ 必应搜索 MCP Server（Bing API 或已有服务）
                                     → 结果归一化 → {available, results, citations, message}
```

启动装配：

```
backend/main.py lifespan
  └─ if mcp_enabled（或 provider==bing_mcp）:
       MCPClientManager(server_url 或 command).connect() → list_tools()
       → 按 mcp_tool_allowlist 过滤
       → 注册为 MCPTool(BaseTool) 进 ToolRegistry / 供 WebSearchTool 调用
       → 失败仅告警，不阻塞启动
```

---

## 4. 模块设计（仅必应单工具）

### 4.1 新增 `agent_service/mcp/`

```
agent_service/mcp/
├── __init__.py
└── client.py         # MCPClientManager：连接管理、call_tool、归一化
```

**`client.py` — `MCPClientManager`**（只连 Streamable HTTP，单工具）

```python
class MCPClientManager:
    def __init__(self, *, server_url: str, timeout=30.0, retry=2): ...
    async def ensure_connected(self) -> None:      # 懒连接 + 指数退避重连，asyncio.Lock 串行化
    async def list_tools(self) -> list[dict]:      # 包装 mcp.ClientSession.list_tools()
    async def call_tool(self, name: str, arguments: dict) -> dict:
        # 1) 校验 name 在白名单（bing_mcp_tool_name）
        # 2) session.call_tool(name, arguments=...) → CallToolResult
        # 3) _normalize_result() 解析 text 块 JSON → {"results": [...]}
    async def close(self) -> None: ...
```

要点：
- **持久连接 + 失败重建**：首次使用连接，缓存 `ClientSession`；调用异常时断开并重连（≤ retry 次，指数退避）。避免每请求建连的开销。
- **并发安全**：`ClientSession` 底层 HTTP 传输非严格并发安全，用一把 `asyncio.Lock` 串行化 `call_tool`（本项目并发量低，串行足够；后续可升级为连接池）。
- **归一化**：MCP `CallToolResult.content` 是 `TextContent/ImageContent` 块，把文本按 JSON 解析（容错 `json_repair`）为 `{"results":[...]}`。

### 4.2 改造 `agent_service/tools/web_search.py`

`_execute_bing_mcp` 从占位改为真实调用，保持契约：

```python
async def _execute_bing_mcp(self, query, max_results) -> dict:
    mcp = get_mcp_manager()                       # 模块级单例（lifespan 注入）
    if mcp is None:
        return {"available": False, "results": [], "citations": [],
                "message": "必应中文搜索 MCP 未初始化"}
    try:
        raw = await mcp.call_tool(settings.bing_mcp_tool_name,
                                  {"query": query, "max_results": max(1, min(max_results, 10))})
    except Exception as exc:
        return {"available": False, "results": [], "citations": [],
                "message": f"必应搜索 MCP 不可用: {exc.__class__.__name__}"}
    return _normalize_search_result(raw)          # → {available, results, citations, message}
```

**不做通用 `MCPTool` 适配器**（决策确认）：本次只接必应单工具，`WebSearchTool` 直接持有 `MCPClientManager` 引用即可；未来要接更多 MCP 工具时再补 `tools/mcp_tool.py` 通用适配层。

### 4.3 改造 `backend/main.py`

`lifespan` 中初始化并注入 MCP 客户端（供 `WebSearchTool` 使用）：

```python
app.state.mcp_manager = None
if settings.mcp_enabled and settings.bing_mcp_server_url:
    from agent_service.mcp.client import MCPClientManager
    app.state.mcp_manager = MCPClientManager(
        server_url=settings.bing_mcp_server_url,
        timeout=settings.mcp_client_timeout,
    )
    try:
        await app.state.mcp_manager.ensure_connected()
        await app.state.mcp_manager.list_tools()
    except Exception as exc:
        logger.warning("MCP 客户端初始化失败，联网检索降级: %s", exc.__class__.__name__)
```

关闭时 `await app.state.mcp_manager.close()`。

---

## 5. 配置项（`backend/config.py`）

```python
# ===== MCP 客户端（doc 20）=====
mcp_enabled: bool = False                 # 总开关；开启后启动时连接 MCP
mcp_client_timeout: float = 30.0
mcp_connect_retry: int = 2
mcp_tool_allowlist: list[str] = ["bing_web_search"]   # 安全白名单：只允许调用该 MCP 工具

# 必应搜索 MCP（Streamable HTTP）
web_search_provider: str = "tavily"       # 已有：tavily | bing_mcp
bing_mcp_server_url: str = ""             # 已有：外部 MCP 服务器地址
bing_mcp_tool_name: str = "bing_web_search"  # 已有：调用的 MCP 工具名
bing_mcp_timeout: float = 30.0
```

---

## 6. 必应 MCP 服务器契约（客户端侧约定）

### 工具定义（`tools/list` 返回）

```json
{
  "name": "bing_web_search",
  "description": "用必应搜索引擎检索中文网页，返回标题、链接与摘要",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "max_results": {"type": "integer", "minimum": 1, "maximum": 10}
    },
    "required": ["query"]
  }
}
```

### `tools/call` 返回（text 内容为 JSON）

```json
{"results": [
  {"title": "...", "url": "https://...", "snippet": "...", "published_date": "2024-01-01"}
]}
```

### 客户端归一化

```python
citations = [{
    "source_type": "web",
    "title": r.get("title"),
    "url": r.get("url"),
    "text": str(r.get("snippet") or "")[:300],
} for r in raw.get("results", [])]
```

---

## 7. 安全设计

| 风险 | 缓解 |
|---|---|
| MCP 服务器暴露危险工具被 Agent 误调 | `mcp_tool_allowlist` 白名单，只注册/放行指定工具名 |
| 搜索结果夹带 Prompt 注入指令 | MCP 返回文本进入 Agent prompt 前用 `<doc>` 数据边界包裹（doc 19 §5.7） |
| 参数注入 | `call_tool` 前按 inputSchema 白名单过滤 kwargs，不转发任意字段 |
| 必应 Key 泄露 | **推荐 MCP 服务器侧持有 Key**，LawRAG 只调用工具；如需用户级 Key，复用 `user_llm_config`（`config_type='bing'`）+ `ToolContext` |
| 未授权 MCP 服务 | 服务器地址来自配置而非用户输入；stdio 命令固定白名单 |

---

## 8. 服务器侧契约（外部服务器须满足）

**本次不自建服务器**（决策确认：外部已有）。外部必应 MCP 服务器只需满足：

- 传输：**Streamable HTTP**，启动后 `initialize` 可握手。
- 暴露工具 `bing_web_search`，inputSchema：`{query: string 必填, max_results: integer 1-10}`。
- `tools/call` 的 text 内容为 JSON：`{"results": [{"title","url","snippet","published_date"}]}`。

参考契约（若对方服务器格式不同，客户端 `_normalize_search_result` 做字段映射即可，见 §6）。

---

## 9. 实施步骤

| 步骤 | 内容 | 产出 |
|---|---|---|
| S1 | `uv add mcp` | 官方 Python SDK 依赖 |
| S2 | `config.py` 新增 §5 配置项 | 配置块 |
| S3 | `agent_service/mcp/client.py` | MCP 客户端（Streamable HTTP） |
| S4 | 改造 `web_search.py` `_execute_bing_mcp` | bing_mcp 真实调用 + 结果归一化 |
| S5 | `backend/main.py` lifespan 装配 | 启动连接 + 白名单校验 |
| S6 | `tests/test_mcp_client.py` | mock 会话：call_tool 归一化 / 降级契约 / Agent 零改动 |
| S7 | 联调真实必应 MCP 服务器 | 填 `bing_mcp_server_url` + `web_search_provider=bing_mcp` 走通案例检索 |

## 10. 验证方式

- **单测**：`MCPTool` 归一化、`WebSearchTool` bing_mcp 分支、降级契约（复用 `tests/test_case_analysis_tools.py` 现有降级断言）。
- **集成**：起本地/远程必应 MCP 服务器 → `web_search_provider=bing_mcp` → `case_analysis` 检索返回中文结果并进入 `citations`。
- **回归**：`uv run python -m compileall backend agent_service` + `uv run python -m unittest discover -s tests`。
- **降级验证**：停掉 MCP 服务器 → 对话仍可用，案例 Agent 返回"联网搜索不可用"降级结果，不崩溃。

---

## 11. 决策已确认

1. **服务器形态**：外部已有 Streamable HTTP 服务器（实施时需提供 `bing_mcp_server_url`）。
2. **适配范围**：仅必应搜索单工具，不做通用 MCP 适配层。
3. **鉴权**：必应 Key 由 MCP 服务器侧持有，LawRAG 不管理用户级 Key。
