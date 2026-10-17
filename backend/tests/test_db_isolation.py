import pytest

import conftest


def test_real_database_file_is_never_touched_by_the_test_suite():
    """Regression guard: nothing in the test suite (the `client` fixture's
    TestClient, in particular -- its app lifespan calls init_db) may ever
    migrate or write to the real backend/job_friend.db. If this fails, some
    code path is reading app.config.settings.db_path directly instead of
    going through a path that tests can override."""
    if conftest.REAL_DB_MTIME_AT_SESSION_START is None:
        pytest.skip("job_friend.db doesn't exist in this environment")
    current_mtime = conftest.REAL_DB_PATH.stat().st_mtime
    assert current_mtime == conftest.REAL_DB_MTIME_AT_SESSION_START
