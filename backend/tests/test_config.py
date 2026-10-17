import os

from app.config import Settings


def test_defaults():
    s = Settings(_env_file=None)
    assert s.lm_studio_base_url == "http://localhost:1234/v1"
    assert s.top_k == 5
    assert s.near_duplicate_threshold == 0.9


def test_env_override(monkeypatch):
    monkeypatch.setenv("JOB_FRIEND_TOP_K", "10")
    s = Settings(_env_file=None)
    assert s.top_k == 10
