"""首页 Dashboard 聚合接口,返回首页所需的统计、列表、图表与系统状态数据。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.schemas.dashboard import DashboardOverviewResponse
from backend.schemas.response import ApiResponse
from backend.services import dashboard as dashboard_service
from backend.services.auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get(
    "/overview",
    response_model=ApiResponse[DashboardOverviewResponse],
    summary="获取首页聚合数据",
    description="返回当前用户首页所需的统计、列表、图表与系统状态聚合数据。",
)
async def get_dashboard_overview(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = 7,
) -> ApiResponse[DashboardOverviewResponse]:
    """聚合首页数据。"""
    if days not in (7, 14, 30):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="days 仅支持 7、14 或 30",
        )
    data = await dashboard_service.build_dashboard_overview(db, current_user, trend_days=days)
    return ApiResponse(data=data)
