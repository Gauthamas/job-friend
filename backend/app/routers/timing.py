import sqlite3

from fastapi import APIRouter, Depends, Query

from app.api_schemas import TimingHistoryResponse
from app.config import settings
from app.deps import get_db
from app.run_timing import average_seconds

router = APIRouter(prefix="/api/timing-history", tags=["timing"])


@router.get("", response_model=TimingHistoryResponse)
def get_timing_history(
    phase: str = Query(..., pattern="^(extraction|judging|threads)$"),
    conn: sqlite3.Connection = Depends(get_db),
):
    stats = average_seconds(conn, phase=phase, model=settings.llm_model)
    return TimingHistoryResponse(**stats)
