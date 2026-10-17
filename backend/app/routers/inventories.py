import json
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.api_schemas import (
    CommitRequest,
    CommitResponse,
    CommittedRole,
    CommittedUnit,
    DraftRoles,
    InventoryDetailResponse,
    InventoryListItem,
    InventoryListResponse,
    InventoryRoleOut,
    UnitOut,
    UnitSearchResponse,
    UnitSearchResultOut,
)
from app.db import connect
from app.deps import get_db, get_db_path, get_embedding_client, get_llm_client
from app.embeddings import embed_units
from app.extraction.pdf import extract_text
from app.judging import ensure_model_not_busy
from app.llm.base import LLMClient
from app.llm.embedding_client import EmbeddingClient
from app.llm.incremental_resume_parser import IncrementalResumeParser
from app.llm.runner import run_task_streaming
from app.llm.tasks import RESUME_STRUCTURE
from app.profiles import get_or_create_default_profile
from app.search import search_units


router = APIRouter(prefix="/api/inventories", tags=["inventories"])


def _sse(event: str, **payload) -> str:
    return f"data: {json.dumps({'event': event, **payload})}\n\n"


@router.post("")
def create_inventory(
    name: str = Form(...),
    profile_id: Optional[int] = Form(None),
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_db),
    llm_client: LLMClient = Depends(get_llm_client),
    db_path: str = Depends(get_db_path),
):
    ensure_model_not_busy(conn)
    if not file and not text:
        raise HTTPException(400, "Provide either a PDF file or pasted text")
    if file and text:
        raise HTTPException(400, "Provide only one of file or text, not both")

    if file:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(400, "Uploaded file must be a PDF")
        resume_text = extract_text(file.file.read())
        source_file = file.filename
    else:
        resume_text = text
        source_file = None

    if not resume_text.strip():
        raise HTTPException(400, "No text could be extracted from the input")

    resolved_profile_id = profile_id or get_or_create_default_profile(conn)

    cursor = conn.execute(
        "INSERT INTO inventory (profile_id, name, source_file) VALUES (?, ?, ?)",
        (resolved_profile_id, name, source_file),
    )
    conn.commit()
    inventory_id = cursor.lastrowid

    def event_stream():
        # Uses its own short-lived connection rather than the injected `conn`:
        # the request's dependency-scoped connection isn't guaranteed to
        # outlive this generator, which keeps running after the route
        # function itself has returned the StreamingResponse.
        parser = IncrementalResumeParser()
        outcome = None

        for event in run_task_streaming(llm_client, RESUME_STRUCTURE, resume_text):
            if event[0] == "delta":
                for pevent in parser.feed(event[1]):
                    yield _sse(pevent.kind, role_index=pevent.role_index, **pevent.data)
            else:
                outcome = event[1]

        if outcome.status == "error":
            cleanup_conn = connect(db_path)
            cleanup_conn.execute("DELETE FROM inventory WHERE id = ?", (inventory_id,))
            cleanup_conn.commit()
            cleanup_conn.close()
            # Deliberately not deleting anything client-side: the UI keeps
            # whatever roles/bullets already streamed in and just shows this
            # as an error banner alongside them.
            yield _sse("error", message="Could not structure the resume text into roles and bullets")
            return

        draft = DraftRoles(roles=outcome.data.roles)
        yield _sse("done", inventory_id=inventory_id, draft=draft.model_dump())

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{inventory_id}/commit", response_model=CommitResponse)
def commit_inventory(
    inventory_id: int,
    body: CommitRequest,
    conn: sqlite3.Connection = Depends(get_db),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
):
    inventory = conn.execute(
        "SELECT id FROM inventory WHERE id = ?", (inventory_id,)
    ).fetchone()
    if not inventory:
        raise HTTPException(404, "Inventory not found")
    ensure_model_not_busy(conn)

    committed_roles: list[CommittedRole] = []
    all_unit_ids: list[int] = []

    for role in body.roles:
        role_cursor = conn.execute(
            "INSERT INTO role (inventory_id, company, title, start_date, end_date, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (inventory_id, role.company, role.title, role.start_date, role.end_date, role.sort_order),
        )
        role_id = role_cursor.lastrowid

        committed_units: list[CommittedUnit] = []
        for unit in role.units:
            unit_cursor = conn.execute(
                "INSERT INTO unit (role_id, text, source, sort_order, context, contribution, outcome, skills_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    role_id, unit.text, unit.source, unit.sort_order,
                    unit.context, unit.contribution, unit.outcome, unit.skills_json,
                ),
            )
            unit_id = unit_cursor.lastrowid
            all_unit_ids.append(unit_id)
            committed_units.append(CommittedUnit(id=unit_id, **unit.model_dump()))

        committed_roles.append(CommittedRole(
            id=role_id, company=role.company, title=role.title,
            start_date=role.start_date, end_date=role.end_date,
            sort_order=role.sort_order, units=committed_units,
        ))

    conn.commit()

    embed_units(conn, all_unit_ids, embedding_client)

    return CommitResponse(inventory_id=inventory_id, roles=committed_roles)


@router.get("/{inventory_id}/search", response_model=UnitSearchResponse)
def search_inventory_units(
    inventory_id: int,
    q: str = Query(""),
    conn: sqlite3.Connection = Depends(get_db),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
):
    inventory = conn.execute(
        "SELECT id FROM inventory WHERE id = ?", (inventory_id,)
    ).fetchone()
    if not inventory:
        raise HTTPException(404, "Inventory not found")
    ensure_model_not_busy(conn)

    results = search_units(conn, inventory_id, q, embedding_client)
    return UnitSearchResponse(results=[UnitSearchResultOut(**r.__dict__) for r in results])


@router.get("", response_model=InventoryListResponse)
def list_inventories(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT i.id, i.name, i.created_at, "
        "  COUNT(DISTINCT r.id) AS role_count, "
        "  COUNT(DISTINCT CASE WHEN u.deleted = 0 THEN u.id END) AS unit_count "
        "FROM inventory i "
        "LEFT JOIN role r ON r.inventory_id = i.id "
        "LEFT JOIN unit u ON u.role_id = r.id "
        "GROUP BY i.id ORDER BY i.created_at DESC"
    ).fetchall()
    return InventoryListResponse(inventories=[
        InventoryListItem(
            id=row["id"], name=row["name"], created_at=row["created_at"],
            role_count=row["role_count"], unit_count=row["unit_count"],
        )
        for row in rows
    ])


@router.get("/{inventory_id}", response_model=InventoryDetailResponse)
def get_inventory(
    inventory_id: int, include_discarded: bool = Query(False), conn: sqlite3.Connection = Depends(get_db),
):
    inventory = conn.execute(
        "SELECT id, name FROM inventory WHERE id = ?", (inventory_id,)
    ).fetchone()
    if not inventory:
        raise HTTPException(404, "Inventory not found")

    role_query = "SELECT * FROM role WHERE inventory_id = ?"
    if not include_discarded:
        role_query += " AND discarded_at IS NULL"
    roles = conn.execute(role_query + " ORDER BY sort_order", (inventory_id,)).fetchall()

    role_outs = []
    for role in roles:
        unit_query = "SELECT * FROM unit WHERE role_id = ? AND deleted = 0"
        if not include_discarded:
            unit_query += " AND discarded_at IS NULL"
        units = conn.execute(unit_query + " ORDER BY sort_order", (role["id"],)).fetchall()
        role_outs.append(InventoryRoleOut(
            id=role["id"], company=role["company"], title=role["title"],
            start_date=role["start_date"], end_date=role["end_date"], sort_order=role["sort_order"],
            discarded_at=role["discarded_at"],
            units=[
                UnitOut(
                    id=u["id"], role_id=u["role_id"], text=u["text"], source=u["source"],
                    sort_order=u["sort_order"], context=u["context"], contribution=u["contribution"],
                    outcome=u["outcome"], skills_json=u["skills_json"], discarded_at=u["discarded_at"],
                )
                for u in units
            ],
        ))

    return InventoryDetailResponse(id=inventory["id"], name=inventory["name"], roles=role_outs)


@router.delete("/{inventory_id}", status_code=204)
def discard_inventory(inventory_id: int, conn: sqlite3.Connection = Depends(get_db)):
    inventory = conn.execute(
        "SELECT id FROM inventory WHERE id = ?", (inventory_id,)
    ).fetchone()
    if not inventory:
        raise HTTPException(404, "Inventory not found")

    role_count = conn.execute(
        "SELECT COUNT(*) AS c FROM role WHERE inventory_id = ?", (inventory_id,)
    ).fetchone()["c"]
    if role_count > 0:
        raise HTTPException(400, "Inventory has saved data and cannot be discarded")

    conn.execute("DELETE FROM inventory WHERE id = ?", (inventory_id,))
    conn.commit()
