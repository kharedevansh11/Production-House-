"""Pass a rendered file only when the hook, length, and daily cap all hold."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def probe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not path.is_file():
        return None
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    try:
        return float(completed.stdout.strip())
    except ValueError:
        return None


def scheduled_today(state: dict, now: datetime) -> int:
    count = 0
    for run in state.get("runs") or []:
        if run.get("status") != "scheduled":
            continue
        raw = run.get("scheduled_date")
        if not raw:
            continue
        when = datetime.fromisoformat(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=now.tzinfo)
        if when.astimezone(now.tzinfo).date() == now.date():
            count += 1
    return count


def review(produced: dict, brief: dict, state: dict, config: dict, now: datetime | None = None) -> dict:
    zone = ZoneInfo(config["timezone"])
    now = now or datetime.now(zone)
    if now.tzinfo is None:
        now = now.replace(tzinfo=zone)
    else:
        now = now.astimezone(zone)
    cap = int(config["daily_cap"])
    used = scheduled_today(state, now)
    path = Path(produced["video"])
    reasons = []
    if produced.get("template") != "hypit-chat-scene":
        reasons.append("render did not come from the local Hypit template")
    if not path.is_file() or path.stat().st_size <= 0:
        reasons.append("video file is missing")
    if produced.get("hook") != brief.get("hook"):
        reasons.append("opening line is not the hook the strategist kept")
    low = int(config["script"]["min_seconds"])
    high = int(config["script"]["max_seconds"])
    claimed = int(produced.get("duration_seconds") or 0)
    measured = probe_duration(path) if path.is_file() else None
    duration = measured if measured is not None else claimed
    if duration < low or duration > high + 1:
        reasons.append(f"duration {duration:.1f}s is outside {low}-{high}s")
    if used >= cap:
        reasons.append(f"daily cap of {cap} is already scheduled")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "scheduled_today": used,
        "duration_seconds": duration,
    }
