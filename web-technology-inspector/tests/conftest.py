import pytest

from web_inspector.config import settings


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Each test gets its own data folder, so labels, preferences or history
    saved on this machine never change a test's result."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
