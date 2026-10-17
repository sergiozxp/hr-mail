"""Where hr-mail finds its bundled programs and keeps its data."""

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    """Folder that contains hr-mail.exe (or the repo root when run from source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bin_dir() -> Path:
    return app_dir() / "bin"


def mercury_exe() -> Path:
    return bin_dir() / "mercury" / "mercury.exe"


def pat_exe() -> Path:
    return bin_dir() / "pat" / "pat.exe"


def data_dir() -> Path:
    """Per-user data folder: %LOCALAPPDATA%\\hr-mail (created on demand)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / "hr-mail"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pat_dir() -> Path:
    """Private Pat folder, so a user's own Pat install is never touched."""
    path = data_dir() / "pat"
    path.mkdir(parents=True, exist_ok=True)
    return path
