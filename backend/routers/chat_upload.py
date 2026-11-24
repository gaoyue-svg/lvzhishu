"""会话临时文件上传与合同审查报告导出接口。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.database import get_db
from backend.models.user import User
from backend.schemas.chat_upload import ChatUploadResponse
from backend.schemas.response import ApiResponse
from backend.services import chat_upload as chat_upload_service
from backend.services.auth import get_current_user
from backend.storage.oss import OSSClient, get_oss
from backend.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/agent", tags=["Agent"])


@router.post("/upload", response_model=ApiResponse[ChatUploadResponse])
async def upload_chat_file(
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    oss: Annotated[OSSClient, Depends(get_oss)],
    file: UploadFile = File(...),
    conversation_id: str | None = Form(default=None),
) -> ApiResponse[ChatUploadResponse]:
    """上传会话文件并解析为 Markdown，返回文件引用供后续对话请求携带。

    支持 Word/PDF/TXT/HTML/图片（含扫描件）；解析结果仅存临时表，不写入知识库。
    """
    conv_id = int(conversation_id) if conversation_id and conversation_id.isdigit() else None
    record = await chat_upload_service.upload_chat_file(db, current_user.id, file, oss, conv_id)
    if record.parse_status == "pending" and record.oss_key:
        background_tasks.add_task(chat_upload_service.parse_chat_upload, record.id, oss)
    return ApiResponse(data=_to_upload_response(record))


@router.get("/upload/{upload_id}", response_model=ApiResponse[ChatUploadResponse])
async def get_chat_upload_status(
    upload_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ChatUploadResponse]:
    """查询会话附件的后台解析状态，供前端轮询。"""
    record = await chat_upload_service.get_upload(db, upload_id, current_user.id)
    return ApiResponse(data=_to_upload_response(record))


def _to_upload_response(record) -> ChatUploadResponse:
    """把会话附件记录转换为统一响应。"""
    error_message = None
    if record.parse_status == "failed":
        error_message = (record.parse_warnings or ["解析失败，请上传更清晰的文档"])[-1]
    return ChatUploadResponse(
        upload_id=str(record.id),
        filename=record.filename,
        file_type=record.file_type,
        doc_type=record.doc_type,
        parse_status=record.parse_status,
        char_count=len(record.raw_markdown or ""),
        clause_count=record.clause_count or 0,
        parse_warnings=record.parse_warnings or [],
        error_message=error_message,
    )


@router.get("/upload/{upload_id}/report")
async def export_contract_report(
    upload_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """导出合同审查报告为 .docx（需分析完成后调用）。"""
    record = await chat_upload_service.get_upload(db, upload_id, current_user.id)
    if record.analysis_status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="合同分析尚未完成，无法导出报告")

    from backend.services.report_exporter import build_contract_report_docx

    docx_bytes = build_contract_report_docx(
        report_markdown=record.analysis_report or "",
        elements=record.analysis_elements,
        summary=record.analysis_summary,
        filename=record.filename,
    )
    safe_name = Path(record.filename).stem or "合同"
    # 中文文件名不能直接放 Content-Disposition 的 filename（HTTP 头仅支持 latin-1），
    # 必须用 RFC 5987 的 filename*=UTF-8'' 编码，否则导出必然抛 UnicodeEncodeError。
    from urllib.parse import quote

    download_name = f"{safe_name}审查报告.docx"
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(download_name)}"
    }
    return StreamingResponse(
        docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )
