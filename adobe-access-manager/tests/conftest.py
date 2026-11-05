from __future__ import annotations

"""Shared, autouse test fixtures.

`adobe_access.settings_store` caches DB-backed settings at module level (see
its docstring) — safe for the real app (one process, one DB), but multiple
test files each swap `database.DB_PATH` to their own temp DB via a local
`temp_db` fixture. Without resetting the cache between tests, a value read
in one test's temp DB could leak into the next test's, whichever `temp_db`
fixture is in play. Same class of pitfall as the MockAdobeClient singleton
noted elsewhere in this suite — reset explicitly rather than relying on
per-file fixtures to remember to do it.
"""

import logging

import pytest

from adobe_access import database, diagnostics, logging_setup, settings_store


@pytest.fixture(autouse=True, scope="session")
def _test_log_and_database(tmp_path_factory):
    """The test run's own log file and database, never the app's: logs/
    and access_manager.db hold real audit entries and data on a machine that
    also runs the app. Tests with a `temp_db` fixture still swap in their own
    database on top of this one."""
    folder = tmp_path_factory.mktemp("app-data")
    saved = (logging_setup.LOG_DIR, logging_setup.LOG_PATH, diagnostics.LOG_PATH, database.DB_PATH)
    logging_setup.LOG_DIR = folder / "logs"
    logging_setup.LOG_PATH = diagnostics.LOG_PATH = folder / "logs" / "access-manager.log"
    logging_setup._logger = None
    logger = logging.getLogger("adobe_access")
    for handler in list(logger.handlers):  # a file handler opened on the app's log
        logger.removeHandler(handler)
        handler.close()
    database.DB_PATH = folder / "access_manager.db"
    database.initialize()
    yield
    logging_setup.LOG_DIR, logging_setup.LOG_PATH, diagnostics.LOG_PATH, database.DB_PATH = saved


@pytest.fixture(autouse=True)
def _reset_settings_store_cache():
    settings_store._invalidate_cache()
    yield
    settings_store._invalidate_cache()
