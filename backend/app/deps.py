import sqlite3
from typing import Iterator

from fastapi import Depends

from app.config import settings
from app.db import connect
from app.llm.base import LLMClient
from app.llm.embedding_client import EmbeddingClient, LMStudioEmbeddingClient
from app.llm.lmstudio_client import LMStudioClient


def get_db_path() -> str:
    return settings.db_path


def get_db(db_path: str = Depends(get_db_path)) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_llm_client() -> LLMClient:
    return LMStudioClient(settings.lm_studio_base_url, settings.llm_model)


def get_embedding_client() -> EmbeddingClient:
    return LMStudioEmbeddingClient(settings.lm_studio_base_url, settings.embed_model)
