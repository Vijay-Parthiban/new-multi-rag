from __future__ import annotations

import tempfile
from pathlib import Path


def overrides_root() -> Path:
    p = Path(tempfile.gettempdir()) / "rag_prompt_overrides"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _override_path(package_name: str, name: str) -> Path:
    safe_pkg = package_name.replace("/", "_").replace("\\", "_")
    safe_name = name.replace("/", "_").replace("\\", "_")
    if not safe_name.endswith(".txt"):
        safe_name += ".txt"
    return overrides_root() / f"{safe_pkg}__{safe_name}"


def has_override(package_name: str, name: str) -> bool:
    return _override_path(package_name, name).exists()


def read_override(package_name: str, name: str) -> str | None:
    p = _override_path(package_name, name)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def write_override(package_name: str, name: str, content: str) -> None:
    p = _override_path(package_name, name)
    p.write_text(content, encoding="utf-8")


def clear_override(package_name: str, name: str) -> bool:
    p = _override_path(package_name, name)
    if p.exists():
        p.unlink()
        return True
    return False


def clear_all_overrides() -> list[str]:
    root = overrides_root()
    cleared: list[str] = []
    if root.exists():
        for f in root.glob("*.txt"):
            cleared.append(f.name)
            try:
                f.unlink()
            except OSError:
                pass
    return cleared
