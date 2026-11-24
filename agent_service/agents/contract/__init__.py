"""本子包实现合同审查的多阶段子 Agent，基于 BaseAgent 骨架拆分。

子 Agent 职责：
- ClauseAgent: 合同理解，条款结构化与 LLM 补充分类
- RuleAgent: 规则检测，对每条条款跑确定性规则
- LegalRAGAgent: 法律 RAG 检索，对高风险条款查相关法条
- RiskReportAgent: 风险分析与报告生成，汇总三源输出结构化风险
- ContractElementsAgent: 要素提取与摘要，输出结构化要素表
"""

from .clause_agent import ClauseAgent
from .elements_agent import ContractElementsAgent
from .legal_rag_agent import LegalRAGAgent
from .risk_report_agent import RiskReportAgent
from .rule_agent import RuleAgent

__all__ = [
    "ClauseAgent",
    "ContractElementsAgent",
    "LegalRAGAgent",
    "RiskReportAgent",
    "RuleAgent",
]
