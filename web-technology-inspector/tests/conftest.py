import logging

import pytest

from web_inspector import logging_setup
from web_inspector.config import settings


@pytest.fixture(autouse=True, scope="session")
def _test_log_file(tmp_path_factory):
    """The test run's own log file, never the app's logs/: mock scans and
    AEM lookups would otherwise mix with real ones on a machine that also
    runs the app."""
    folder = tmp_path_factory.mktemp("logs")
    saved = (logging_setup.LOG_DIR, logging_setup.LOG_PATH)
    logging_setup.LOG_DIR, logging_setup.LOG_PATH = folder, folder / "web-technology-inspector.log"
    logging_setup._logger = None
    logger = logging.getLogger("web_inspector")
    for handler in list(logger.handlers):  # a file handler opened on the app's log
        logger.removeHandler(handler)
        handler.close()
    yield
    logging_setup.LOG_DIR, logging_setup.LOG_PATH = saved


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Each test gets its own data folder, so labels, preferences or history
    saved on this machine never change a test's result."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
