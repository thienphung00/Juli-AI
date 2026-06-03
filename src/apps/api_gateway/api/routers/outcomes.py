"""Campaign outcome recording — placeholder until P1-3 (issue queue)."""

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/outcomes", tags=["outcomes"])


@router.post("")
async def record_outcome() -> None:
    """Record realized campaign outcomes for calibration (P1-3)."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Outcome recording is planned for P1-3",
    )
