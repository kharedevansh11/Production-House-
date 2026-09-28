"""Append-only supervisor log. Other roles return results; only this module writes the file."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config_loader import DATA

LOG_PATH = DATA / "supervisor.jsonl"
STATE_PATH = DATA / "state.json"


def log(run_id: str, agent: str, event: str, summary: str, **extra) -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "agent": agent,
        "event": event,
        "summary": summary,
    }
    record.update(extra)
    with LOG_PATH.open("a") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_log(path: Path = LOG_PATH) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_state(path: Path = STATE_PATH) -> dict:
    if not path.is_file():
        return {"runs": []}
    return json.loads(path.read_text())


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
