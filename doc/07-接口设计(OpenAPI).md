# 接口设计（OpenAPI）

## 1. 统一响应

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

## 2. 用户接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/auth/register | 注册 |
| POST | /api/auth/login | 登录 |
| POST | /api/auth/logout | 退出 |
| GET | /api/user/profile | 当前用户信息 |
| PUT | /api/user/profile | 修改用户信息 |
| PUT | /api/user/password | 修改密码 |

## 3. 知识库接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/kb | 知识库列表 |
| POST | /api/kb | 创建知识库 |
| GET | /api/kb/{id} | 知识库详情 |
| PUT | /api/kb/{id} | 修改知识库 |
| DELETE | /api/kb/{id} | 删除知识库 |

## 4. 文档接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/document/upload | 上传文档 |
| GET | /api/document | 文档列表 |
| GET | /api/document/{id} | 文档详情 |
| POST | /api/document/{id}/parse | 重新解析 |
| DELETE | /api/document/{id} | 删除文档 |

## 5. Chunk 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/chunk | 查询 Chunk |
| GET | /api/chunk/{id} | Chunk 详情 |
| PUT | /api/chunk/{id} | 修改 Chunk |
| POST | /api/chunk/{id}/embedding | 重建单个 Chunk 向量 |

## 6. Embedding 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/embedding/rebuild | 批量重建 Embedding |
| GET | /api/embedding/task/{id} | 查询任务状态 |
| GET | /api/embedding/stats | Embedding 统计 |

## 7. 聊天接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/chat | 普通聊天 |
| POST | /api/chat/stream | 流式聊天 |
| GET | /api/conversation | 会话列表 |
| GET | /api/conversation/{id} | 会话详情 |
| DELETE | /api/conversation/{id} | 删除会话 |

## 8. Agent 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/agent/law-qa | 法律咨询 |
| POST | /api/agent/case-analysis | 案例分析 |
| POST | /api/agent/contract-review | 合同审查 |
| POST | /api/agent/document-generate | 文书生成 |
| GET | /api/agent | Agent 列表 |
| POST | /api/agent | 创建 Agent |
| PUT | /api/agent/{id} | 修改 Agent |

## 9. 检索调试接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/retrieve/debug | 检索调试 |
| POST | /api/retrieve/evaluate | 检索评估 |
| GET | /api/retrieve/trace/{id} | 查看检索 Trace |

## 10. Prompt 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/prompt | Prompt 列表 |
| POST | /api/prompt | 创建 Prompt |
| PUT | /api/prompt/{id} | 修改 Prompt |
| POST | /api/prompt/{id}/publish | 发布版本 |
| POST | /api/prompt/{id}/rollback | 回滚版本 |

## 11. 管理接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/admin/dashboard | Dashboard |
| GET | /api/admin/logs | 日志列表 |
| GET | /api/admin/model | 模型配置列表 |
| POST | /api/admin/model | 新增模型配置 |
| PUT | /api/admin/config | 修改系统配置 |

