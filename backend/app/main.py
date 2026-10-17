from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.judging import close_open_judging_windows
from app.routers import (
    flows,
    inventories,
    jobs,
    judgments,
    letter,
    pairs,
    primary_secondary,
    requirements,
    roles,
    settings as settings_router_module,
    statements,
    threads,
    timing,
    units,
)
from app.settings_store import load_settings_from_db

FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "build"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run migrations once at startup. Routes open their own per-request
    # connection (see app/deps.py) since SQLite connections aren't safe to
    # share across the threads FastAPI uses for sync route handlers.
    # v2 (§3): no in-process worker/queue anymore -- a requirement is either
    # 'pending' or 'done', nothing in between, so there is nothing to
    # recover after a restart. The one thing a restart can leave behind is
    # a job whose judging_deadline is still in the future even though the
    # background task that was running it is gone -- close that window
    # immediately so "Running" doesn't lie.
    conn = init_db(settings.db_path)
    load_settings_from_db(conn)
    conn.close()
    close_open_judging_windows(settings.db_path)

    yield


app = FastAPI(title="Job-Friend", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(inventories.router)
app.include_router(units.router)
app.include_router(roles.router)
app.include_router(flows.router)
app.include_router(jobs.router)
app.include_router(requirements.router)
app.include_router(judgments.router)
app.include_router(pairs.router)
app.include_router(statements.router)
app.include_router(threads.router)
app.include_router(primary_secondary.router)
app.include_router(letter.router)
app.include_router(settings_router_module.router)
app.include_router(settings_router_module.legacy_router)
app.include_router(timing.router)

# Must stay last: a catch-all here would otherwise shadow any API route
# registered after it.
if FRONTEND_DIST.is_dir():
    app.mount("/_app", StaticFiles(directory=FRONTEND_DIST / "_app"), name="frontend-assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # SPA fallback: serve the matching built file if one exists
        # (favicon, robots.txt, ...), else index.html for client-side routing
        # to take over (e.g. /inventories/new, which has no file on disk).
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
