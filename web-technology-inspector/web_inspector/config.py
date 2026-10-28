from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from .utils import harden_file_permissions

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    app_env: str = "development"

    # Mock mode answers scans and AEM lookups from sample data, so the whole
    # scan -> evidence -> history flow can be tried without a browser download,
    # a reachable website, or an AEM token.
    mock_mode: bool = True

    # --- Browser scan --------------------------------------------------------
    # Seconds allowed for the page to load before the scan gives up.
    scan_timeout: int = 45

    # Seconds to wait for network activity to settle after load and after
    # scrolling; tags that fire later than this are not captured.
    settle_seconds: int = 6

    # Open a visible browser window by default. Sites behind bot protection
    # (Akamai, Cloudflare and similar) often block headless browsers.
    show_browser: bool = False

    # --- Local data ----------------------------------------------------------
    # Folder (relative to the project root unless absolute) for the scan history DB.
    data_dir: str = "data"

    model_config = SettingsConfigDict(env_file=ENV_PATH, extra="ignore")

    @property
    def data_path(self) -> Path:
        path = Path(self.data_dir)
        return path if path.is_absolute() else PROJECT_ROOT / path


settings = Settings()


def harden_env_file() -> None:
    """Restrict .env to the owning user only.
    Called from app.py's startup, not at import time."""
    if ENV_PATH.exists():
        harden_file_permissions(ENV_PATH)
