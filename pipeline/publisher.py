"""Schedule a passed video through Upload-Post. Facebook is not in this API."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from reviewer import scheduled_today


def next_slot(now: datetime, used: int, config: dict) -> datetime | None:
    if used >= int(config["daily_cap"]):
        return None
    zone = ZoneInfo(config["timezone"])
    local = now.astimezone(zone).replace(second=0, microsecond=0)
    start = int(config["day_start_hour"])
    end = int(config["day_end_hour"])
    slot = local + timedelta(minutes=15)
    if slot.hour < start:
        slot = slot.replace(hour=start, minute=0)
    elif slot.hour >= end:
        day = slot + timedelta(days=1)
        slot = day.replace(hour=start, minute=0)
    return slot


def publish(produced: dict, brief: dict, state: dict, config: dict, now: datetime | None = None) -> dict:
    zone = ZoneInfo(config["timezone"])
    now = now.astimezone(zone) if now else datetime.now(zone)
    used = scheduled_today(state, now)
    slot = next_slot(now, used, config)
    if slot is None:
        return {"status": "held", "reason": "daily cap is already scheduled"}
    api_key = os.environ.get("UPLOAD_POST_API_KEY", "").strip()
    if not api_key:
        return {"status": "held", "reason": "UPLOAD_POST_API_KEY is not set", "scheduled_date": slot.isoformat()}
    script = brief["script"]
    caption = script.get("caption") or brief["hook"]
    tags = " ".join(script.get("hashtags") or [])
    description = f"{caption}\n{tags}".strip()
    platforms = list(config["platforms"])
    profile = config["upload_post"]["profile"]
    data = {
        "user": profile,
        "title": brief["hook"][:100],
        "platform[]": platforms,
        "async_upload": "true",
        "scheduled_date": slot.strftime("%Y-%m-%dT%H:%M:%S"),
        "timezone": config["timezone"],
    }
    if "tiktok" in platforms:
        data["tiktok_title"] = description
        data["post_mode"] = "MEDIA_UPLOAD"
    if "instagram" in platforms:
        data["instagram_title"] = description
        data["media_type"] = "REELS"
    if "youtube" in platforms:
        data["youtube_title"] = brief["hook"][:100]
        data["youtube_description"] = description
        data["privacyStatus"] = "public"
    path = produced["video"]
    with open(path, "rb") as handle:
        response = httpx.post(
            config["upload_post"]["api_base"].rstrip("/") + "/api/upload",
            headers={"Authorization": f"Apikey {api_key}"},
            data=data,
            files={"video": (os.path.basename(path), handle, "video/mp4")},
            timeout=180,
        )
    if response.status_code not in (200, 201, 202):
        return {"status": "held", "reason": f"Upload-Post {response.status_code}: {response.text[:400]}"}
    return {
        "status": "scheduled",
        "scheduled_date": slot.isoformat(),
        "platforms": platforms,
        "response": response.json(),
    }
