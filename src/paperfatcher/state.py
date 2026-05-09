"""picked.json store with atomic writes (load + add)."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _read(path: Path) -> dict:
    if not path.exists():
        return {"ids": [], "updated_at": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"ids": [], "updated_at": None}


def load(path: Path) -> set[str]:
    return set(_read(path).get("ids", []))


def add(path: Path, paper_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read(path)
    ids = list(dict.fromkeys([*data.get("ids", []), paper_id]))
    data["ids"] = ids
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    fd, tmp = tempfile.mkstemp(prefix=".picked.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
