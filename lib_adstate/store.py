"""Preset persistence for the ADetailer State Manager.

Presets are plain JSON files on disk, one file per preset, under
``<models_path>/adetailer-presets/{tab,full}``. Files are only ever written by
an explicit save, so editing the UI after loading a preset never mutates it.

The models directory is used because it is the only user-data location the webui
keeps out of its own git working tree (``/models/**/*`` is in the stock
``.gitignore``), so presets survive a ``git clean`` during an update. It also
follows ``--models-dir``, so installs that share a models drive share presets.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = 1

Kind = Literal["tab", "full"]

_KIND_DIRS: dict[str, str] = {"tab": "tab", "full": "full"}

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_COLLAPSE = re.compile(r"\s+")

# Names Windows refuses to use for a file, regardless of extension.
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_base_dir_override: Path | None = None


class PresetError(Exception):
    """Raised for user-correctable preset problems (bad name, missing file)."""


def set_base_dir(path: str | Path | None) -> None:
    """Override the preset root. Used by the tests; unset with ``None``."""
    global _base_dir_override
    _base_dir_override = None if path is None else Path(path)


def base_dir() -> Path:
    if _base_dir_override is not None:
        return _base_dir_override

    try:
        from modules.paths_internal import models_path
    except Exception:
        return Path.cwd() / "models" / "adetailer-presets"

    return Path(models_path, "adetailer-presets")


def kind_dir(kind: Kind) -> Path:
    if kind not in _KIND_DIRS:
        raise PresetError(f"Unknown preset kind: {kind!r}")
    return base_dir() / _KIND_DIRS[kind]


def sanitize_name(name: str) -> str:
    """Turn user input into a safe, stable file stem.

    Raises ``PresetError`` when nothing usable is left.
    """
    if not isinstance(name, str):
        raise PresetError("Preset name must be text")

    name = unicodedata.normalize("NFC", name)
    name = _INVALID_CHARS.sub(" ", name)
    name = _COLLAPSE.sub(" ", name).strip().strip(".")

    if not name:
        raise PresetError("Preset name is empty")

    if name.upper() in _RESERVED:
        name = f"{name}_"

    # Keep well clear of MAX_PATH limits while leaving room for the suffix.
    return name[:96]


def preset_path(kind: Kind, name: str) -> Path:
    return kind_dir(kind) / f"{sanitize_name(name)}.json"


def list_presets(kind: Kind) -> list[str]:
    directory = kind_dir(kind)
    if not directory.is_dir():
        return []

    names = (p.stem for p in directory.glob("*.json") if p.is_file())
    return sorted(names, key=str.casefold)


def exists(kind: Kind, name: str) -> bool:
    return preset_path(kind, name).is_file()


def save_preset(kind: Kind, name: str, payload: dict[str, Any]) -> Path:
    path = preset_path(kind, name)
    path.parent.mkdir(parents=True, exist_ok=True)

    document = {
        "schema": SCHEMA_VERSION,
        "kind": kind,
        "name": path.stem,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **payload,
    }

    # Write via a temporary file so an interrupted save cannot corrupt an
    # existing preset.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

    return path


def load_preset(kind: Kind, name: str) -> dict[str, Any]:
    path = preset_path(kind, name)
    if not path.is_file():
        raise PresetError(f'Preset "{name}" not found')

    try:
        # ``utf-8-sig`` transparently accepts the BOM that Notepad and
        # PowerShell add, so hand-edited or shared presets still load.
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise PresetError(f'Could not read preset "{name}": {exc}') from exc

    if not isinstance(document, dict):
        raise PresetError(f'Preset "{name}" is malformed')

    schema = document.get("schema")
    if schema is not None and schema > SCHEMA_VERSION:
        raise PresetError(
            f'Preset "{name}" was written by a newer version (schema {schema})'
        )

    stored_kind = document.get("kind")
    if stored_kind is not None and stored_kind != kind:
        raise PresetError(f'Preset "{name}" is a "{stored_kind}" preset, not "{kind}"')

    return document


def delete_preset(kind: Kind, name: str) -> None:
    path = preset_path(kind, name)
    if not path.is_file():
        raise PresetError(f'Preset "{name}" not found')
    path.unlink()
