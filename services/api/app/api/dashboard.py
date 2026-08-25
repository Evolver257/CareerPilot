from fastapi import APIRouter, Depends

from app.api.dependencies import get_dashboard_service
from app.schemas.dashboard import DashboardRead
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardRead)
async def get_dashboard(
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardRead:
    return await service.overview()
