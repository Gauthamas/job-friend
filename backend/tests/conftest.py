import pathlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import init_db
from app.deps import get_db_path, get_embedding_client, get_llm_client
from app.llm.mock_client import MockLLMClient
from app.llm.mock_embedding_client import MockEmbeddingClient
from app.main import app

# Regression guard for test_db_isolation.py: the real db file's mtime,
# snapshotted once before any test runs (pytest_configure fires before
# collection, so this can never race a test that touches the file first).
REAL_DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "job_friend.db"
REAL_DB_MTIME_AT_SESSION_START: float | None = None


def pytest_configure(config: pytest.Config) -> None:
    global REAL_DB_MTIME_AT_SESSION_START
    if REAL_DB_PATH.exists():
        REAL_DB_MTIME_AT_SESSION_START = REAL_DB_PATH.stat().st_mtime


@pytest.fixture
def db(tmp_path) -> sqlite3.Connection:
    conn = init_db(str(tmp_path / "test.db"))
    yield conn
    conn.close()


@pytest.fixture
def mock_llm() -> MockLLMClient:
    return MockLLMClient()


@pytest.fixture
def mock_embedder() -> MockEmbeddingClient:
    return MockEmbeddingClient()


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "test.db")
    init_db(path).close()
    return path


@pytest.fixture
def client(db_path, mock_llm, mock_embedder, monkeypatch) -> TestClient:
    # app.main's lifespan calls init_db(settings.db_path) directly -- it
    # runs outside request scope, so dependency_overrides (request-scoped)
    # can't reach it. Patching the Settings singleton itself is what keeps
    # TestClient's startup/shutdown from ever touching the real db file.
    monkeypatch.setattr(settings, "db_path", db_path)

    app.dependency_overrides[get_db_path] = lambda: db_path
    app.dependency_overrides[get_llm_client] = lambda: mock_llm
    app.dependency_overrides[get_embedding_client] = lambda: mock_embedder
    yield TestClient(app)
    app.dependency_overrides.clear()
