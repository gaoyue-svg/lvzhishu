"""本文件提供合同审查任务的创建、进度查询与结果获取接口。

支持两种创建方式：
1. /review：基于已入库的 document_id 创建审查（需先走知识库上传解析链路）。
2. /upload-review：直接上传合同文件，临时解析后入队审查，不写入知识库表。
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ConfigDict
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, get_redis
from backend.models.contract import ContractRisk
from backend.models.knowledge import KnowledgeDocument
from backend.models.task import TaskLog
from backend.models.user import User
from backend.schemas.contract import (
    ContractDocumentResponse,
    ContractReviewRequest,
    ContractReviewResultResponse,
    ContractReviewTaskResponse,
    ContractRiskItem,
    ContractTaskStatusResponse,
)
from backend.schemas.response import ApiResponse
from backend.services.auth import get_current_user
from backend.services.document import _detect_file_type, _save_upload_to_temp
from backend.services.parser import parse_document
from backend.utils.logger import get_logger
from backend.worker.task_queue import CONTRACT_REVIEW_STREAM, TaskQueue

router = APIRouter(prefix="/api/contract", tags=["contract"])
logger = get_logger(__name__)

# 直接上传审查模式标记，Worker 据此走"从 input_params 读合同"分支
UPLOAD_REVIEW_SOURCE = "upload"


@router.post("/review", response_model=ApiResponse[ContractReviewTaskResponse])
async def create_review_task(
    body: ContractReviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis | None, Depends(get_redis)],
) -> ApiResponse[ContractReviewTaskResponse]:
    """创建合同审查异步任务，入队 Redis Stream 由 Worker 执行规则检测。"""
    if redis is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis 不可用")

    # 校验文档归属与解析状态
    doc = await db.get(KnowledgeDocument, body.document_id)
    if doc is None or doc.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="合同文档不存在")
    if doc.parse_status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="合同文档未完成解析，请等待解析完成后再审查",
        )

    # 创建 task_log 任务记录
    task_log = TaskLog(
        task_type="contract_review",
        resource_type="knowledge_document",
        resource_id=doc.id,
        user_id=current_user.id,
        status="pending",
        input_params={
            "document_id": doc.id,
            "contract_type": body.contract_type,
            "review_level": body.review_level,
            "review_dimensions": body.review_dimensions,
        },
    )
    db.add(task_log)
    await db.flush()

    task = {
        "task_id": task_log.id,
        "document_id": doc.id,
        "user_id": current_user.id,
        "contract_type": body.contract_type,
        "review_level": body.review_level,
        "review_dimensions": body.review_dimensions,
    }
    try:
        msg_id = await TaskQueue(redis).enqueue(CONTRACT_REVIEW_STREAM, task)
        task_log.input_params = {**task_log.input_params, "stream_msg_id": msg_id}
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("入队合同审查任务失败 task_id=%s", task_log.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="入队审查任务失败，请重试",
        )

    await db.refresh(task_log)
    return ApiResponse(
        data=ContractReviewTaskResponse(
            task_id=task_log.id,
            document_id=doc.id,
            status=task_log.status,
        )
    )


@router.get("/task/{task_id}", response_model=ApiResponse[ContractTaskStatusResponse])
async def get_task_status(
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ContractTaskStatusResponse]:
    """查询合同审查任务进度。"""
    task_log = await db.get(TaskLog, task_id)
    if task_log is None or task_log.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    output = task_log.output_result or {}
    return ApiResponse(
        data=ContractTaskStatusResponse(
            task_id=task_log.id,
            document_id=task_log.resource_id or 0,
            status=task_log.status,
            progress=_calc_progress(task_log.status),
            risk_count=output.get("risk_count", 0),
            high_count=output.get("high_count", 0),
            medium_count=output.get("medium_count", 0),
            low_count=output.get("low_count", 0),
            error_message=task_log.error_message,
            created_at=task_log.created_at,
            finished_at=task_log.finished_at,
        )
    )


@router.get("/task/{task_id}/result", response_model=ApiResponse[ContractReviewResultResponse])
async def get_task_result(
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ContractReviewResultResponse]:
    """获取合同审查完整结果，包含风险列表与评分。"""
    task_log = await db.get(TaskLog, task_id)
    if task_log is None or task_log.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if task_log.status != "done":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"任务未完成，当前状态: {task_log.status}",
        )

    # 加载风险列表
    result = await db.execute(
        select(ContractRisk)
        .where(ContractRisk.task_id == task_id)
        .order_by(
            ContractRisk.risk_level,
            ContractRisk.created_at,
        )
    )
    risks = [
        ContractRiskItem.model_validate(risk, from_attributes=True)
        for risk in result.scalars().all()
    ]

    output = task_log.output_result or {}
    return ApiResponse(
        data=ContractReviewResultResponse(
            task_id=task_log.id,
            document_id=task_log.resource_id or 0,
            status=task_log.status,
            risk_score=output.get("risk_score", 0),
            risks=risks,
            report=output.get("report"),
            contract_name=output.get("contract_name"),
            parties=output.get("parties", []),
        )
    )


def _calc_progress(status: str) -> int:
    """根据任务状态估算进度百分比。"""
    mapping = {
        "pending": 0,
        "analyzing": 50,
        "reporting": 80,
        "done": 100,
        "failed": 100,
    }
    return mapping.get(status, 0)


@router.post("/upload-review", response_model=ApiResponse[ContractReviewTaskResponse])
async def upload_and_review(
    file: Annotated[UploadFile, File()],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis | None, Depends(get_redis)],
    contract_type: Annotated[str, Form()] = "other",
    review_level: Annotated[str, Form()] = "standard",
    review_dimensions: Annotated[list[str], Form()] = ["legality", "fairness", "completeness"],
) -> ApiResponse[ContractReviewTaskResponse]:
    """直接上传合同文件审查，临时解析后入队，不写入知识库表。

    流程：校验文件 → 保存临时文件 → parse_document 解析成 markdown →
    创建 task_log（input_params 存 contract_markdown + source=upload）→ 入队审查。
    """
    if redis is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis 不可用")

    # 校验文件类型并保存到临时文件
    file_type = _detect_file_type(file.filename or "")
    tmp_path, _size, _ = await _save_upload_to_temp(file)
    filename = file.filename or "contract"

    try:
        # 解析成 markdown，parse_document 内部已包装同步解析逻辑
        markdown = await parse_document(str(tmp_path), file_type)
        if not markdown or not markdown.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="合同解析未产出文本，请检查文件内容或改用其他格式",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("合同解析失败 filename=%s", filename)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"合同解析失败: {exc.__class__.__name__}",
        )
    finally:
        # best-effort 清理临时文件
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    # 创建 task_log，合同原文存 input_params，不写 knowledge_document
    task_log = TaskLog(
        task_type="contract_review",
        resource_type="contract_upload",
        resource_id=None,
        user_id=current_user.id,
        status="pending",
        input_params={
            "source": UPLOAD_REVIEW_SOURCE,
            "filename": filename,
            "contract_markdown": markdown,
            "contract_type": contract_type,
            "review_level": review_level,
            "review_dimensions": review_dimensions,
        },
    )
    db.add(task_log)
    await db.flush()

    task = {
        "task_id": task_log.id,
        "document_id": 0,  # 直接上传模式无 document_id
        "user_id": current_user.id,
        "source": UPLOAD_REVIEW_SOURCE,
        "contract_type": contract_type,
        "review_level": review_level,
        "review_dimensions": review_dimensions,
    }
    try:
        msg_id = await TaskQueue(redis).enqueue(CONTRACT_REVIEW_STREAM, task)
        task_log.input_params = {**task_log.input_params, "stream_msg_id": msg_id}
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("入队合同审查任务失败 task_id=%s", task_log.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="入队审查任务失败，请重试",
        )

    await db.refresh(task_log)
    return ApiResponse(
        data=ContractReviewTaskResponse(
            task_id=task_log.id,
            document_id=0,
            status=task_log.status,
        )
    )


@router.get("/task/{task_id}/document", response_model=ApiResponse[ContractDocumentResponse])
async def get_task_document(
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ApiResponse[ContractDocumentResponse]:
    """获取直接上传审查任务的合同原文 Markdown，供结果页左侧展示。"""
    task_log = await db.get(TaskLog, task_id)
    if task_log is None or task_log.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    params = task_log.input_params or {}
    if params.get("source") != UPLOAD_REVIEW_SOURCE:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该任务非直接上传模式，无合同原文",
        )

    return ApiResponse(
        data=ContractDocumentResponse(
            task_id=task_log.id,
            filename=params.get("filename", "contract"),
            markdown=params.get("contract_markdown", ""),
        )
    )
