"""本文件提供可替换的中文分词与 token 计数抽象。"""

from abc import ABC, abstractmethod
from pathlib import Path

from backend.utils.tokenizer import count_tokens, truncate_to_tokens


class BaseTokenizer(ABC):
    """所有关键词检索分词器的抽象接口。"""

    @abstractmethod
    def tokenize(self, text: str) -> list[str]:
        """将文本转换为检索 token 列表。"""


class JiebaTokenizer(BaseTokenizer):
    """使用 jieba 精确模式分词，并支持加载法律自定义词典。"""

    def __init__(self, dict_path: str | None = None):
        """初始化独立 Tokenizer，避免污染 jieba 全局状态。"""
        import jieba

        self._tokenizer = jieba.Tokenizer()
        if dict_path and Path(dict_path).is_file():
            self._tokenizer.load_userdict(dict_path)

    def tokenize(self, text: str) -> list[str]:
        """过滤空白后返回 jieba 精确模式结果。"""
        return [token.strip() for token in self._tokenizer.cut(text or "", cut_all=False) if token.strip()]


class HanLPTokenizer(BaseTokenizer):
    """预留的 HanLP 分词器适配器，启用前需注入可调用模型。"""

    def __init__(self, model=None):
        """保存外部提供的 HanLP 模型。"""
        self.model = model

    def tokenize(self, text: str) -> list[str]:
        """调用 HanLP 模型执行分词。"""
        if self.model is None:
            raise RuntimeError("HanLP 分词器模型未配置")
        return list(self.model(text or ""))


__all__ = [
    "BaseTokenizer",
    "HanLPTokenizer",
    "JiebaTokenizer",
    "count_tokens",
    "truncate_to_tokens",
]
