import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.api_schemas import MatchedSectionsPatchRequest, SettingOut, SettingsPatchRequest, SettingsResponse
from app.deps import get_db
from app.settings_store import InvalidSettingValue, all_settings, reset_setting, set_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Milestone 6's ad hoc endpoint -- kept working as a thin alias over the
# general settings store (§7 part A point 3).
legacy_router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
def get_settings(conn: sqlite3.Connection = Depends(get_db)):
    return SettingsResponse(settings=[SettingOut(**s) for s in all_settings(conn)])


@router.patch("", response_model=SettingsResponse)
def patch_settings(body: SettingsPatchRequest, conn: sqlite3.Connection = Depends(get_db)):
    for key, value in body.values.items():
        try:
            set_setting(conn, key, value)
        except InvalidSettingValue as e:
            raise HTTPException(400, str(e))
    return SettingsResponse(settings=[SettingOut(**s) for s in all_settings(conn)])


@router.delete("/{key}", response_model=SettingsResponse)
def delete_setting(key: str, conn: sqlite3.Connection = Depends(get_db)):
    try:
        reset_setting(conn, key)
    except InvalidSettingValue as e:
        raise HTTPException(404, str(e))
    return SettingsResponse(settings=[SettingOut(**s) for s in all_settings(conn)])


@legacy_router.get("/matched-sections")
def get_matched_sections(conn: sqlite3.Connection = Depends(get_db)):
    from app.settings_store import current_value
    return {"value": current_value("matched_sections")}


@legacy_router.patch("/matched-sections")
def patch_matched_sections(body: MatchedSectionsPatchRequest, conn: sqlite3.Connection = Depends(get_db)):
    if body.value < 0:
        raise HTTPException(400, "Must be 0 or more")
    value = set_setting(conn, "matched_sections", body.value)
    return {"value": value}
