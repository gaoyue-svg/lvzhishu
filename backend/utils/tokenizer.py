"""本文件提供跨服务复用的 token 计数与文本截断工具函数。"""


def count_tokens(text: str, model_name: str = "cl100k_base") -> int:
    """优先使用 tiktoken 计数，模型未知时回退到稳健字符估算。"""
    if not text:
        return 0
    try:
        import tiktoken

        try:
            encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(1, len(text) // 2)


def truncate_to_tokens(text: str, max_tokens: int, model_name: str = "cl100k_base") -> str:
    """按 token 上限截断文本；不可用 tiktoken 时使用字符数近似。"""
    if max_tokens <= 0 or not text:
        return ""
    try:
        import tiktoken

        try:
            encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        tokens = encoding.encode(text)
        return text if len(tokens) <= max_tokens else encoding.decode(tokens[:max_tokens])
    except Exception:
        return text[: max_tokens * 2]

