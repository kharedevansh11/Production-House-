"""studio.py tests. Models are faked; ffmpeg runs for real when it is installed."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import media  # noqa: E402
import studio  # noqa: E402

RHYME = """[verse]
Twinkle twinkle little star
How I wonder what you are
Up above the world so high
Like a diamond in the sky
"""


class PureTests(unittest.TestCase):
    def test_song_scenes_drop_section_tags_and_keep_words(self):
        scenes = studio.scenes_from(RHYME, studio.KINDS["rhyme"])
        self.assertEqual(scenes, ["Twinkle twinkle little star\nHow I wonder what you are", "Up above the world so high\nLike a diamond in the sky"])

    def test_voice_scenes_split_on_sentences(self):
        scenes = studio.scenes_from("One. Two!  Three? Four.", studio.KINDS["facts"])
        self.assertEqual(scenes, ["One.", "Two!", "Three?", "Four."])

    def test_spread_covers_window_in_order(self):
        spans = media.spread(["aa", "a", "aaa"], 2.0, 8.0)
        self.assertEqual(spans[0][0], 2.0)
        self.assertAlmostEqual(spans[-1][1], 8.0, places=2)
        self.assertAlmostEqual(spans[0][1] - spans[0][0], 2.0, places=2)

    def test_short_windows_respect_cap_and_merge_tail(self):
        spans = [(i * 10.0, i * 10.0 + 10) for i in range(7)]  # 70 s
        windows = media.short_windows(spans, 30, 12)
        for first, last in windows:
            self.assertLessEqual(spans[last][1] - spans[first][0], 30)
        self.assertEqual(windows[0][0], 0)
        self.assertEqual(windows[-1][1], 6)
        # 3 scenes then 3 scenes then a 10 s tail that cannot merge without breaking 30 s
        self.assertEqual(windows, [(0, 2), (3, 5), (6, 6)])
        # a short tail merges when it fits
        self.assertEqual(media.short_windows([(0, 20), (20, 25)], 30, 12), [(0, 1)])

    def test_quiz_script_round_trips(self):
        items = [("How many bones?", "206"), ("Largest organ?", "Skin")]
        text = studio.quiz_text("Body Quiz", items)
        self.assertEqual(studio.parse_quiz(text + "not a question line\n"), ("Body Quiz", items))

    def test_quiz_parts_stay_under_cap(self):
        # 20 questions of 4 s each, 8 s of intro and outro per reel, 50 s cap: 10 per reel
        parts = studio.quiz_parts([4.0] * 20, 8.0, 50.0)
        self.assertEqual(parts, [(0, 10), (10, 20)])
        self.assertEqual(studio.quiz_parts([4.0] * 3, 8.0, 50.0), [(0, 3)])

    def test_cast_gives_each_character_a_distinct_valid_speaker(self):
        chars = studio.cast({"characters": [
            {"id": "maa", "gender": "female", "speaker": "Rohit"},
            {"id": "bahu", "gender": "female", "speaker": "Divya"},
            {"id": "beta", "gender": "male"},
        ]})
        self.assertEqual({k: v["speaker"] for k, v in chars.items()}, {"maa": "Divya", "bahu": "Rani", "beta": "Rohit"})
        self.assertEqual(chars["beta"]["name"], "beta")

    def test_ass_time(self):
        self.assertEqual(media.ass_time(3725.5), "1:02:05.50")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
class EndToEndTests(unittest.TestCase):
    def test_make_publishes_full_video_and_shorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cfg = {
                "ollama_url": "http://x/v1",
                "ollama_model": "m",
                "work_dir": str(tmp / "work"),
                "publish_dir": str(tmp / "public"),
                "public_url": "http://nas:9103",
                "short_max_seconds": 6,
                "short_min_seconds": 2,
            }

            def fake_speak(text, voice, speed, out, cfg):
                media.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=440:d=2.5", str(out)])
                return media.duration(out)

            def fake_paint(prompts, negative, out_dir, cfg, seed):
                paths = []
                for index, _ in enumerate(prompts):
                    path = out_dir / f"scene{index:02d}.png"
                    media.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=768x512", "-frames:v", "1", str(path)])
                    paths.append(path)
                return paths

            plan = {"title": "Four facts", "description": "d", "hashtags": ["#a"], "character": "", "images": ["p1", "p2"]}
            patches = {
                (studio, "ask"): lambda cfg, system, user: plan,
                (studio, "unload_ollama"): lambda cfg: None,
                (studio, "log"): lambda *a, **k: None,
                (media, "speak"): fake_speak,
                (media, "paint"): fake_paint,
            }
            saved = {key: getattr(*key) for key in patches}
            for (module, name), fn in patches.items():
                setattr(module, name, fn)
            try:
                links = studio.make("facts", "One fact. Two facts. Three facts. Four facts.", None, None, cfg)
            finally:
                for (module, name), fn in saved.items():
                    setattr(module, name, fn)

            folder = Path(cfg["publish_dir"]) / links["page"].rstrip("/").rsplit("/", 1)[1]
            self.assertTrue(links["page"].startswith("http://nas:9103/"))
            full = folder / "full.mp4"
            self.assertAlmostEqual(media.duration(full), 10.0, delta=0.3)
            shorts = sorted(folder.glob("short-*.mp4"))
            self.assertEqual(len(shorts), 2)  # 4 scenes x 2.5 s, 6 s cap
            size = media.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(shorts[0])])
            self.assertEqual(size.strip(), "1080,1920")
            self.assertTrue((folder / "thumb.jpg").is_file())
            meta = json.loads((folder / "meta.json").read_text())
            self.assertEqual(meta["title"], "Four facts")
            self.assertIn("full.mp4", (folder / "index.html").read_text())
            self.assertIn(folder.name, (Path(cfg["publish_dir"]) / "index.html").read_text())

    def test_quiz_reel_is_vertical_and_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cfg = {"ollama_url": "http://x/v1", "ollama_model": "m", "work_dir": str(tmp / "w"),
                   "publish_dir": str(tmp / "p"), "public_url": "http://nas:9103"}

            def fake_speak(text, voice, speed, out, cfg):
                media.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=300:d=0.5", "-ar", "24000", str(out)])
                return media.duration(out)

            saved = (studio.unload_ollama, studio.log, media.speak)
            studio.unload_ollama, studio.log, media.speak = (lambda cfg: None), (lambda *a, **k: None), fake_speak
            try:
                script = studio.quiz_text("Body Quiz", [(f"Question {i}?", str(i)) for i in range(1, 5)])
                links = studio.make("quiz", script, None, None, cfg)
            finally:
                studio.unload_ollama, studio.log, media.speak = saved
            folder = Path(cfg["publish_dir"]) / links["page"].rstrip("/").rsplit("/", 1)[1]
            reel = folder / "reel-1.mp4"
            size = media.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(reel)])
            self.assertEqual(size.strip(), "1080,1920")
            # intro + 4 x (q + gap + ding + a + pause) + outro + tail
            expected = 0.5 + 0.45 + 4 * (0.5 + 0.25 + 0.18 + 0.5 + 0.45) + 0.5 + 0.9
            self.assertAlmostEqual(media.duration(reel), expected, delta=0.3)
            self.assertEqual((tmp / "w").glob("*/quiz1.ass").__next__().read_text().count("✓"), 4)

    def _ghar(self, line_seconds: float):
        tmp = Path(tempfile.mkdtemp())
        cfg = {"ollama_url": "http://x/v1", "ollama_model": "m", "image_model": "x", "work_dir": str(tmp / "w"),
               "publish_dir": str(tmp / "p"), "public_url": "http://nas:9103", "short_max_seconds": 50}
        story = {
            "title": "WiFi password", "caption": "Ghar ghar ki kahani?", "hashtags": ["#desi"], "setting": "kitchen",
            "characters": [{"id": "maa", "name": "Mummy", "gender": "female", "speaker": "Divya", "look": "woman"},
                           {"id": "beta", "name": "Beta", "gender": "male", "speaker": "Rohit", "look": "boy"}],
            "lines": [{"who": "maa", "text": "WiFi ka password kya hai?", "hi": "WiFi का पासवर्ड क्या है?"},
                      {"who": "beta", "text": "Pehle khana khao.", "hi": "पहले खाना खाओ।"},
                      {"who": "ghost", "text": "dropped: no such character"}],
        }

        spoken = []

        def fake_speak_hindi(texts, speakers, out_dir, cfg):
            paths = []
            spoken.extend(texts)
            for index, _ in enumerate(texts):
                path = out_dir / f"line{index:02d}.wav"
                media.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=f=220:d={line_seconds}", "-ar", "24000", str(path)])
                paths.append(path)
            return paths

        def fake_paint(prompts, negative, out_dir, cfg, seed, size=(768, 512), model=None, prefix="scene"):
            paths = []
            for index, _ in enumerate(prompts):
                path = out_dir / f"{prefix}{index:02d}.png"
                media.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={size[0]}x{size[1]}", "-frames:v", "1", str(path)])
                paths.append(path)
            return paths

        def fake_talk(face, audio, out, cfg):
            media.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(face), "-i", str(audio), "-shortest",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
            return out

        patches = {(studio, "unload_ollama"): lambda cfg: None, (studio, "log"): lambda *a, **k: None,
                   (media, "speak_hindi"): fake_speak_hindi, (media, "paint"): fake_paint, (media, "talk"): fake_talk}
        saved = {key: getattr(*key) for key in patches}
        for (module, name), fn in patches.items():
            setattr(module, name, fn)
        try:
            links = studio.make("ghar", json.dumps(story, ensure_ascii=False), None, None, cfg)
        finally:
            for (module, name), fn in saved.items():
                setattr(module, name, fn)
            shutil.rmtree(tmp / "w", ignore_errors=True)
        self.assertEqual(spoken[:2], ["WiFi का पासवर्ड क्या है?", "पहले खाना खाओ।"])  # voice gets Devanagari
        folder = Path(cfg["publish_dir"]) / links["page"].rstrip("/").rsplit("/", 1)[1]
        return folder

    def test_ghar_reel_is_vertical_with_one_segment_per_line(self):
        folder = self._ghar(3.0)
        reel = folder / "reel.mp4"
        size = media.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(reel)])
        self.assertEqual(size.strip(), "1080,1920")
        self.assertAlmostEqual(media.duration(reel), 6.0, delta=0.3)
        self.assertIn("Mummy: WiFi ka password", json.loads((folder / "meta.json").read_text())["script"])

    def test_ghar_speeds_up_slightly_long_scenes_to_fit_the_cap(self):
        folder = self._ghar(27.0)  # 54 s of speech, 50 s cap: sped up about 9%
        self.assertLessEqual(media.duration(folder / "reel.mp4"), 50.0)


if __name__ == "__main__":
    unittest.main()
