"""文件哈希辅助工具。"""

import hashlib

from fastapi import UploadFile


async def sha256(file: UploadFile) -> str:
    """流式计算上传文件的 SHA256，避免将文件全部载入内存。"""
    digest = hashlib.sha256()
    while chunk := await file.read(1024 * 1024):
        digest.update(chunk)
    await file.seek(0)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """计算字节数据的 SHA256。"""
    return hashlib.sha256(data).hexdigest()
