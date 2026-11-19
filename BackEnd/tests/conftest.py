import os
import shutil
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROD_DB = BACKEND_DIR / "margrakshak.db"
TEST_DB = BACKEND_DIR / "test_margrakshak.db"

# Isolate test session to test_margrakshak.db before any app modules or models are loaded
os.environ["MARGRAKSHAK_SQLITE_DB"] = "test_margrakshak.db"
if PROD_DB.exists():
    shutil.copy2(PROD_DB, TEST_DB)

import pytest
from app.core.database import engine


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    """Ensure engine is disposed and test database is removed after test suite finishes."""
    yield
    engine.dispose()
    if TEST_DB.exists():
        try:
            os.remove(TEST_DB)
        except Exception:
            pass


