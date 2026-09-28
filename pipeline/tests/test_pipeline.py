"""Unit tests for the local pipeline. No network, no Hypit render."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import openshorts_clip  # noqa: E402
import producer  # noqa: E402
import publisher  # noqa: E402
import reviewer  # noqa: E402
import strategist  # noqa: E402
from llm import parse_json_object  # noqa: E402

ZONE = ZoneInfo("Asia/Kolkata")

CONFIG = {
    "niche": "home coffee",
    "timezone": "Asia/Kolkata",
    "daily_cap": 3,
    "platforms": ["tiktok", "instagram", "youtube"],
    "day_start_hour": 8,
    "day_end_hour": 22,
    "ollama": {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b"},
    "hypit": {"generation_models": False, "canvas_width": 1080, "canvas_height": 1920},
    "script": {"min_seconds": 20, "max_seconds": 30},
    "openshorts": {
        "api_url": "http://127.0.0.1:8000",
        "allowlist": {
            "urls": ["https://www.youtube.com/watch?v=owned"],
            "channel_ids": ["UCowned"],
            "handles": ["mychannel"],
            "local_dirs": [],
        },
    },
    "upload_post": {"profile": "default", "api_base": "https://api.upload-post.com"},
}


def fake_complete(base_url, model, system, user):
    if "exactly 5 angles" in system or "5 angles" in system:
        return json.dumps({"angles": [
            {"topic": f"angle {i}", "visual_style": "chat captions", "why": "original"}
            for i in range(5)
        ]})
    if "high-retention" in system:
        return json.dumps({
            "hook": "draft hook",
            "lines": ["The usual way wastes a minute.", "Do this instead.", "That is the payoff."],
            "cta": "Save this for tomorrow morning.",
            "caption": "A better morning cup.",
            "hashtags": ["#coffee", "#morning"],
            "duration_seconds": 24,
        })
    return json.dumps({
        "hooks": [
            {"line": "Stop buying coffee pods.", "trigger": "surprise", "score": 9},
            {"line": "Your kettle is the problem.", "trigger": "curiosity", "score": 7},
            {"line": "This costs less than one cafe visit.", "trigger": "desire", "score": 6},
            {"line": "You already own the tool.", "trigger": "ego", "score": 5},
            {"line": "Most people scorch the grounds.", "trigger": "fear", "score": 4},
        ],
        "winner": "Stop buying coffee pods.",
    })


class PipelineTests(unittest.TestCase):
    def test_parse_json_fenced(self):
        parsed = parse_json_object('```json\n{"ok": 1}\n```')
        self.assertEqual(parsed["ok"], 1)

    def test_research_writes_original_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            strategist.DATA = Path(tmp)
            brief = strategist.research(CONFIG, search_fn=lambda niche: ["pods are expensive"], complete_fn=fake_complete)
        self.assertEqual(len(brief["angles"]), 5)
        self.assertEqual(len(brief["hooks"]), 5)
        self.assertEqual(brief["hook"], "Stop buying coffee pods.")
        self.assertEqual(strategist.spoken_lines(brief)[0], brief["hook"])
        self.assertGreaterEqual(brief["script"]["duration_seconds"], 20)
        self.assertLessEqual(brief["script"]["duration_seconds"], 30)

    def test_svml_is_local_template(self):
        brief = {
            "niche": "home coffee",
            "hook": "Stop buying coffee pods.",
            "chosen_angle": {"topic": "Skip the pods"},
            "script": {
                "lines": ["Grind coarser.", "That is the payoff."],
                "cta": "Save this.",
                "duration_seconds": 24,
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            svml = producer.write_svml(brief, Path(tmp) / "reel.svml", CONFIG)
        self.assertIn("@example/chat-scene@1", svml)
        self.assertIn("Stop buying coffee pods.", svml)
        self.assertNotIn("seedance", svml.lower())
        self.assertNotIn("http", svml.lower())

    def test_allowlist_rejects_other_youtube_videos(self):
        allow = CONFIG["openshorts"]["allowlist"]
        self.assertFalse(openshorts_clip.source_allowed("https://www.youtube.com/watch?v=someoneelse", allow))
        self.assertTrue(openshorts_clip.source_allowed("https://www.youtube.com/watch?v=owned", allow))
        self.assertTrue(openshorts_clip.source_allowed("https://www.youtube.com/channel/UCowned/videos", allow))
        self.assertTrue(openshorts_clip.source_allowed("https://www.youtube.com/@mychannel/videos", allow))
        self.assertFalse(openshorts_clip.source_allowed("https://vimeo.com/123", allow))

    def test_allowlist_local_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "mine.mp4"
            video.write_bytes(b"not a real mp4")
            allow = {**CONFIG["openshorts"]["allowlist"], "local_dirs": [tmp]}
            self.assertTrue(openshorts_clip.source_allowed(str(video), allow))
            self.assertFalse(openshorts_clip.source_allowed("/tmp/other.mp4", allow))

    def test_reviewer_cap_and_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "clip.mp4"
            video.write_bytes(b"mp4")
            brief = {"hook": "Stop buying coffee pods.", "script": {"duration_seconds": 24}}
            produced = {"video": str(video), "hook": brief["hook"], "duration_seconds": 24, "template": "hypit-chat-scene"}
            now = datetime(2026, 9, 28, 11, 0, tzinfo=ZONE)
            state = {"runs": [
                {"status": "scheduled", "scheduled_date": "2026-09-28T09:00:00+05:30"},
                {"status": "scheduled", "scheduled_date": "2026-09-28T10:00:00+05:30"},
                {"status": "scheduled", "scheduled_date": "2026-09-28T12:00:00+05:30"},
            ]}
            held = reviewer.review(produced, brief, state, CONFIG, now)
            self.assertFalse(held["passed"])
            self.assertEqual(held["scheduled_today"], 3)
            open_state = {"runs": []}
            passed = reviewer.review(produced, brief, open_state, CONFIG, now)
            self.assertTrue(passed["passed"])
            bad = reviewer.review({**produced, "hook": "other"}, brief, open_state, CONFIG, now)
            self.assertFalse(bad["passed"])

    def test_next_slot_stays_in_daytime(self):
        night = datetime(2026, 9, 28, 23, 10, tzinfo=ZONE)
        slot = publisher.next_slot(night, 0, CONFIG)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.hour, 8)
        self.assertEqual(slot.day, 29)
        full = publisher.next_slot(datetime(2026, 9, 28, 12, 0, tzinfo=ZONE), 3, CONFIG)
        self.assertIsNone(full)


if __name__ == "__main__":
    unittest.main()
