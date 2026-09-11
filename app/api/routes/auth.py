from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import require_rate_limited_admin_token

router = APIRouter()


class AdminSessionResponse(BaseModel):
    authenticated: Literal[True]


@router.get("/admin/session", response_model=AdminSessionResponse)
async def get_admin_session(
    _admin: None = Depends(require_rate_limited_admin_token),
) -> AdminSessionResponse:
    return AdminSessionResponse(authenticated=True)
