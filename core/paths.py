"""
Resource / data path resolution for both dev and packaged (.app) runs.

- Read-only resources (web/, example configs) ship inside the bundle and are
  read via ``resource_path``.
- Writable user data (.env, ai_providers.json) must live OUTSIDE the read-only
  .app bundle, so in a frozen build they go to
  ``~/Library/Application Support/Aura``. In dev they stay in the project root
  so behaviour is unchanged.
"""
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Aura"


def is_frozen() -> bool:
    """True when running from a PyInstaller-built bundle."""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Directory holding bundled read-only resources (web/, examples)."""
    if is_frozen():
        # PyInstaller unpacks bundled `datas` here.
        return Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    # Dev: project root (parent of this core/ package).
    return Path(__file__).resolve().parent.parent


def resource_path(*parts) -> str:
    """Absolute path to a bundled read-only resource."""
    return str(resource_dir().joinpath(*parts))


def data_dir() -> Path:
    """Writable directory for user data (.env, ai_providers.json)."""
    if is_frozen():
        d = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        d = resource_dir()  # dev: project root (unchanged behaviour)
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_runtime_files() -> None:
    """
    In a frozen app, seed the writable data dir from bundled templates on first
    run (a build/install step may already have placed real configs there).
    """
    if not is_frozen():
        return
    dd = data_dir()
    rd = resource_dir()

    def _seed(target_name: str, candidates: list[str]) -> None:
        dst = dd / target_name
        if dst.exists():
            return
        for cand in candidates:
            src = rd / cand
            if src.exists():
                shutil.copy2(src, dst)
                return

    _seed("ai_providers.json", ["ai_providers.json", "ai_providers.example.json"])
    _seed(".env", [".env", ".env.example"])
    # Keep an example beside the real file so first-run copy paths still work.
    for ex in ("ai_providers.example.json", ".env.example"):
        src, dst = rd / ex, dd / ex
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
