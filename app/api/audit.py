"""
Audit-Log API Endpoints.

GET /api/audit – Liste der Audit-Einträge (nur Admin), mit Filterung und Pagination.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select, func
from pydantic import BaseModel

from app.core.database import get_session
from app.models import AuditLogEntry, User
from app.auth import require_admin

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntryResponse(BaseModel):
    id: str
    created_at: str
    user_id: Optional[str]
    username: str
    action: str
    resource_type: str
    resource_id: Optional[str]
    details: Optional[Dict[str, Any]]


class AuditListResponse(BaseModel):
    entries: List[AuditEntryResponse]
    total: int
    page: int
    page_size: int


def _parse_iso_datetime(value: Optional[str], param_name: str) -> Optional[datetime]:
    if not value or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ungültiges {param_name}-Format. Erwartet: ISO-Datum/Zeit (YYYY-MM-DD oder YYYY-MM-DDTHH:MM:SS)",
        )


@router.get("", response_model=AuditListResponse)
async def get_audit_log(
    user_id: Optional[str] = Query(None, description="Filter nach User-ID (UUID)"),
    action: Optional[str] = Query(None, description="Filter nach Aktion (z.B. run_start, run_cancel)"),
    resource_type: Optional[str] = Query(None, description="Filter nach Ressourcentyp (pipeline, run, user, settings)"),
    since: Optional[str] = Query(None, description="Nur Einträge ab diesem Zeitpunkt (ISO-Format)"),
    limit: int = Query(50, ge=1, le=500, description="Einträge pro Seite"),
    offset: int = Query(0, ge=0, description="Offset für Pagination"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
) -> AuditListResponse:
    """
    Gibt Audit-Log-Einträge zurück (nur für Admins).
    """
    base_stmt = select(AuditLogEntry)
    count_stmt = select(func.count(AuditLogEntry.id))

    if user_id:
        try:
            uid = UUID(user_id)
            base_stmt = base_stmt.where(AuditLogEntry.user_id == uid)
            count_stmt = count_stmt.where(AuditLogEntry.user_id == uid)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_id muss eine gültige UUID sein",
            )
    if action:
        base_stmt = base_stmt.where(AuditLogEntry.action == action)
        count_stmt = count_stmt.where(AuditLogEntry.action == action)
    if resource_type:
        base_stmt = base_stmt.where(AuditLogEntry.resource_type == resource_type)
        count_stmt = count_stmt.where(AuditLogEntry.resource_type == resource_type)
    since_dt = _parse_iso_datetime(since, "since")
    if since_dt:
        base_stmt = base_stmt.where(AuditLogEntry.created_at >= since_dt)
        count_stmt = count_stmt.where(AuditLogEntry.created_at >= since_dt)

    total = session.exec(count_stmt).one()
    stmt = base_stmt.order_by(AuditLogEntry.created_at.desc()).limit(limit).offset(offset)
    entries = list(session.exec(stmt).all())

    return AuditListResponse(
        entries=[
            AuditEntryResponse(
                id=str(e.id),
                created_at=e.created_at.isoformat(),
                user_id=str(e.user_id) if e.user_id else None,
                username=e.username,
                action=e.action,
                resource_type=e.resource_type,
                resource_id=e.resource_id,
                details=e.details,
            )
            for e in entries
        ],
        total=total,
        page=(offset // limit) + 1 if limit > 0 else 1,
        page_size=limit,
    )
