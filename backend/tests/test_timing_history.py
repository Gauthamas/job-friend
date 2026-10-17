from app.db import connect
from app.run_timing import record_run_timing


def test_timing_history_empty_when_no_history(client):
    resp = client.get("/api/timing-history", params={"phase": "extraction"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sample_size"] == 0
    assert body["avg_seconds_total"] is None


def test_timing_history_averages_recent_rows_for_current_model(client, db_path):
    from app.config import settings

    conn = connect(db_path)
    record_run_timing(
        conn, phase="judging", mode="batch", model=settings.llm_model, thinking=True,
        prompt_version="1", items=3, batch_size=3, seconds_total=30.0, seconds_to_first_result=10.0,
    )
    record_run_timing(
        conn, phase="judging", mode="batch", model=settings.llm_model, thinking=True,
        prompt_version="1", items=3, batch_size=3, seconds_total=50.0, seconds_to_first_result=20.0,
    )
    # A different model's history must not pollute the current model's average.
    record_run_timing(
        conn, phase="judging", mode="batch", model="some-other-model", thinking=True,
        prompt_version="1", items=3, batch_size=3, seconds_total=1000.0, seconds_to_first_result=900.0,
    )
    conn.close()

    resp = client.get("/api/timing-history", params={"phase": "judging"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sample_size"] == 2
    assert body["avg_seconds_total"] == 40.0
    assert body["avg_seconds_to_first_result"] == 15.0


def test_timing_history_rejects_unknown_phase(client):
    resp = client.get("/api/timing-history", params={"phase": "bogus"})
    assert resp.status_code == 422
