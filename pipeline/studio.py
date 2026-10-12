#!/usr/bin/env python3
"""Make one full video plus vertical shorts for a use case, and publish them on the NAS.

    python studio.py rhyme --script twinkle.txt     # your lyrics, sung
    python studio.py facts --topic "space"          # Ollama writes it
    python studio.py scary                          # topic from what is trending
    python studio.py quiz --topic "human body"      # 20-question rapid-fire reels, 50 s or less each
    python studio.py ghar --draft                   # Hindi household scene as editable JSON, then --script it
    python studio.py facts --draft                  # write the script only, check it, then --script it

Script (Ollama) -> voice (Kokoro) or song (ACE-Step) -> pictures (SD 1.5 + LCM)
-> ffmpeg (Ken Burns, captions, shorts) -> publish_dir, served by nginx on the LAN.
"""

from __future__ import annotations

import argparse
import html
import json
import random
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import httpx

import media
from config_loader import load_config
from llm import complete, parse_json_object
from strategist import reddit_snippets
from supervisor import log

KIDS_NEGATIVE = "text, letters, watermark, logo, blurry, deformed, extra limbs, ugly, scary, violent, realistic photo"

KINDS = {
    "rhyme": {
        "about": "Kids nursery rhyme, sung",
        "audio": "song",
        "trend": "nursery rhyme toddlers",
        "lines_per_scene": 2,
        "style": "bright colorful 3D cartoon, cute round characters, pastel colors, children's animation still, soft light",
        "music": "cheerful children's nursery rhyme, ukulele, xylophone, hand claps, bright friendly female vocal, simple catchy melody, 100 bpm",
        "negative": KIDS_NEGATIVE,
        "write": "Write an ORIGINAL nursery rhyme for toddlers aged 2-5: a [verse], a [chorus], a [verse], a [chorus]. "
        "4 short lines per section, simple words, strong end rhymes, playful repetition. "
        "Put each section tag on its own line, e.g. [verse].",
    },
    "scary": {
        "about": "Short creepy story, narrated (no gore)",
        "audio": "voice",
        "voice": "bm_george",
        "speed": 0.95,
        "trend": "subreddit:nosleep",
        "lines_per_scene": 2,
        "style": "dark cinematic horror still, fog, low key lighting, film grain, eerie atmosphere",
        "negative": "text, letters, watermark, logo, blurry, deformed, extra limbs, gore, blood",
        "write": "Write an ORIGINAL first-person creepy story, 150-220 words, with a gripping first sentence and a twist "
        "in the last line. No gore. Do not retell any post you were shown.",
    },
    "facts": {
        "about": "Did-you-know facts, narrated",
        "audio": "voice",
        "voice": "am_michael",
        "speed": 1.0,
        "trend": "subreddit:todayilearned",
        "lines_per_scene": 1,
        "style": "cinematic documentary photograph, dramatic lighting, highly detailed",
        "negative": "text, letters, watermark, logo, blurry, deformed, extra limbs",
        "write": "Write a 45-75 second 'did you know' script: a one-line hook, then 5 surprising facts on ONE topic, "
        "one sentence each, then a one-line question to the viewer. Only use facts stated in the titles you are given, "
        "or facts you are certain are true.",
    },
    "ghar": {
        "about": "Hindi household reel: AI family members talk on camera",
        "audio": "ghar",
        "trend": "subreddit:indiasocial family",
        "write": "Write one short, funny, relatable scene from a middle-class Indian home, the kind Hindi Instagram reels go viral with: "
        "mummy-papa-beta-beti, saas-bahu, nosy relatives, exams, WiFi, AC remote, chai, shaadi pressure, savings, kitchen rules.",
    },
    "quiz": {
        "about": "Rapid-fire 20-question reel: question, answer, box ticks",
        "audio": "quiz",
        "voice": "af_bella",
        "speed": 1.1,
        "trend": "subreddit:todayilearned",
        "write": "Write a rapid-fire quiz on ONE topic people love: the human body, space, animals, geography, food, or history.",
    },
}

WRITE_SYSTEM = """You write scripts for short videos.
Return JSON only: {"title":"","script":""}.
title is under 70 characters. script is the exact words to be spoken or sung, with newlines between lines."""

PLAN_SYSTEM = """You direct the pictures for a narrated video.
Return JSON only: {"title":"","description":"","hashtags":["#tag"],"character":"","images":[""]}.
character describes the recurring main character's look in under 20 words (species, colors, clothes), or "" if none.
images has exactly one entry per scene, in order: what is in the picture, under 35 words, concrete and visual, no words or letters in the picture.
description is 2 sentences for YouTube. hashtags is 3 to 6 tags."""


QUIZ_SYSTEM = """You write rapid-fire quiz reels.
Return JSON only: {"title":"","items":[{"q":"","a":""}]}.
Exactly 20 items. q is one short question, under 12 words. a is the answer, 1 to 4 words, digits for numbers.
Only facts that are well established and that you are certain of. No trick questions, no duplicates.
Order them from easy to most surprising. title is like "20 Questions About the Human Body", under 40 characters."""

GHAR_SYSTEM = """You write Hindi Instagram reels: short scenes from Indian homes, acted by 2 or 3 family members.
Return JSON only:
{"title":"","caption":"","hashtags":["#tag"],"setting":"","characters":[{"id":"maa","name":"Mummy","gender":"female","speaker":"Divya","look":""}],"lines":[{"who":"maa","text":"","hi":""}]}
Rules:
- 6 to 9 lines, about 80 Hindi words in total, so the reel stays under 40 seconds.
- Line 1 is the hook: a relatable conflict that makes people stop scrolling. The last line is the punchline or twist.
- text is the line in everyday spoken Hindi written in English letters (Hinglish), e.g. "Beta, WiFi ka password kya hai?". It is shown as the caption.
- hi is the exact same line in Devanagari script, used only for the voice. English words like WiFi may stay in English letters. No stage directions.
- Clean family humour. No religion, caste, politics, or jokes about anyone's body or looks.
- name is how the family calls them, in English letters (Mummy, Papa, Dadi, Bahu, Beta).
- speaker: female characters use Divya or Rani, male characters use Rohit or Aman; every character gets a different speaker.
- look describes them for a photo: age, clothes, hair, e.g. "Indian woman in her 50s, cotton saree, small bindi, reading glasses".
- setting is the room for a photo, e.g. "middle-class Indian kitchen, steel utensils, gas stove, morning light".
- caption is a Hinglish Instagram caption with a question to drive comments. hashtags is 4 to 6 tags."""

HINDI_SPEAKERS = {"female": ["Divya", "Rani"], "male": ["Rohit", "Aman"]}
REAL_NEGATIVE = "cartoon, anime, painting, illustration, 3d render, deformed, disfigured, extra fingers, blurry, text, watermark, logo"

QUIZ_OUTRO = "How many did you get? Comment your score!"


def ask(cfg: dict, system: str, user: str) -> dict:
    for attempt in range(2):
        try:
            return parse_json_object(complete(cfg["ollama_url"], cfg["ollama_model"], system, user, timeout=900))
        except (ValueError, json.JSONDecodeError):
            if attempt:
                raise


def unload_ollama(cfg: dict) -> None:
    """Free the 4 GB GPU for Stable Diffusion."""
    root = cfg["ollama_url"].rstrip("/").removesuffix("/v1")
    try:
        httpx.post(root + "/api/generate", json={"model": cfg["ollama_model"], "keep_alive": 0}, timeout=60)
    except httpx.HTTPError:
        pass


def write_script(kind: dict, topic: str | None, cfg: dict, system: str = WRITE_SYSTEM) -> dict:
    if topic:
        seed = f"Topic: {topic}"
    else:
        try:
            titles = reddit_snippets(kind["trend"], limit=15)
        except (httpx.HTTPError, ValueError, KeyError):
            titles = []
        shown = "\n".join(f"- {t}" for t in titles) or "- (none; pick a popular evergreen topic)"
        seed = f"Pick the topic most likely to get views right now. Recent popular titles, for inspiration only:\n{shown}"
    return ask(cfg, system, f"{kind['write']}\n\n{seed}")


def scenes_from(script: str, kind: dict) -> list[str]:
    """Split the script into scene captions without changing a word."""
    if kind["audio"] == "song":
        units = [line.strip() for line in script.splitlines() if line.strip() and not re.fullmatch(r"\[.*\]", line.strip())]
    else:
        units = [s for s in re.split(r"(?<=[.!?])\s+", " ".join(script.split())) if s]
    size = kind["lines_per_scene"]
    return ["\n".join(units[i : i + size]) for i in range(0, len(units), size)]


def narrate(texts: list[str], kind: dict, work: Path, cfg: dict) -> tuple[Path, list[tuple[float, float]]]:
    spans, at, parts = [], 0.0, []
    for index, text in enumerate(texts):
        part = work / f"voice{index:02d}.wav"
        seconds = media.speak(text.replace("\n", " "), kind["voice"], kind["speed"], part, cfg)
        spans.append((at, at + seconds))
        at += seconds
        parts.append(part)
    listing = work / "voice.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
    out = work / "narration.wav"
    media.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])
    return out, spans


def song(script: str, texts: list[str], kind: dict, work: Path, cfg: dict) -> tuple[Path, list[tuple[float, float]]]:
    seconds = max(30, min(240, int(len(texts) * kind["lines_per_scene"] * 3.2 + 12)))
    out = media.sing(script, kind["music"], seconds, work / "song.wav", cfg)
    start, end = media.vocal_window(out, cfg)
    spans = media.spread(texts, start, end)
    # stretch first and last scenes so pictures cover the intro and outro too
    spans[0] = (0.0, spans[0][1])
    spans[-1] = (spans[-1][0], media.duration(out))
    return out, spans


def quiz_text(title: str, items: list[tuple[str, str]]) -> str:
    """The quiz as an editable script: a '# title' line, then 'question | answer' lines."""
    return f"# {title}\n" + "".join(f"{q} | {a}\n" for q, a in items)


def parse_quiz(text: str) -> tuple[str, list[tuple[str, str]]]:
    title, items = "Quick Quiz", []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            title = line.lstrip("# ").strip() or title
        elif "|" in line:
            question, answer = (part.strip() for part in line.split("|", 1))
            if question and answer:
                items.append((question, answer))
    return title, items


GAP, DING, PAUSE = 0.25, 0.18, 0.45


def quiz_parts(item_seconds: list[float], fixed_seconds: float, cap: float) -> list[tuple[int, int]]:
    """Split questions into consecutive reels, each with intro and outro, none longer than cap."""
    parts, first, used = [], 0, fixed_seconds
    for index, seconds in enumerate(item_seconds):
        if used + seconds > cap and index > first:
            parts.append((first, index))
            first, used = index, fixed_seconds
        used += seconds
    parts.append((first, len(item_seconds)))
    return parts


def make_quiz(kind: dict, script_text: str, run_id: str, work: Path, cfg: dict) -> dict:
    title, items = parse_quiz(script_text)
    if not items:
        raise ValueError("a quiz script needs 'question | answer' lines")
    unload_ollama(cfg)
    voice, speed = kind["voice"], kind["speed"]
    gap = media.tone(work / "gap.wav", GAP)
    pause = media.tone(work / "pause.wav", PAUSE)
    ding = media.tone(work / "ding.wav", DING, 1320)
    outro = work / "outro.wav"
    outro_seconds = media.speak(QUIZ_OUTRO, voice, speed, outro, cfg) + 2 * PAUSE
    spoken = []
    for index, (question, answer) in enumerate(items):
        q_wav, a_wav = work / f"q{index:02d}.wav", work / f"a{index:02d}.wav"
        spoken.append((q_wav, media.speak(question, voice, speed, q_wav, cfg), a_wav, media.speak(answer, voice, speed, a_wav, cfg)))
    item_seconds = [q + GAP + DING + a + PAUSE for _, q, _, a in spoken]
    # the "Part 1" intro is the longest one a reel can get, so it bounds every part
    longest_intro = media.speak(f"{title} · Part 1. How many can you get right?", voice, speed, work / "intro-probe.wav", cfg)
    ranges = quiz_parts(item_seconds, longest_intro + PAUSE + outro_seconds, float(cfg.get("short_max_seconds", 50)))

    files = {}
    for number, (first, last) in enumerate(ranges, 1):
        heading = title if len(ranges) == 1 else f"{title} · Part {number}"
        intro = work / f"intro{number}.wav"
        at = media.speak(f"{heading}. How many can you get right?", voice, speed, intro, cfg) + PAUSE
        intro_end, parts, timings = at, [intro, pause], []
        for q_wav, q_sec, a_wav, a_sec in spoken[first:last]:
            asked = at
            revealed = at + q_sec + GAP
            at = revealed + DING + a_sec + PAUSE
            parts += [q_wav, gap, ding, a_wav, pause]
            timings.append((asked, revealed, at))
        audio = media.join_audio(parts + [outro, pause, pause], work / f"quiz{number}.wav")
        subs = media.quiz_ass(heading, items[first:last], timings, intro_end, QUIZ_OUTRO, media.duration(audio),
                              work / f"quiz{number}.ass", first_number=first + 1)
        reel = media.quiz_video(subs, audio, work / f"reel-{number}.mp4")
        files[reel.name] = reel
        if number == 1:
            thumb = work / "thumb.jpg"
            media.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{timings[-1][2] - 0.2:.2f}", "-i", str(reel), "-frames:v", "1", "-vf", "scale=720:-2", str(thumb)])
    files["thumb.jpg"] = thumb
    log(run_id, "studio", "audio_ready", f"{len(ranges)} reels")
    meta = {
        "kind": "quiz",
        "title": title,
        "description": f"{len(items)} rapid-fire questions. {QUIZ_OUTRO}",
        "hashtags": ["#quiz", "#trivia", "#didyouknow", "#shorts"],
        "script": script_text,
        "run_id": run_id,
    }
    links = publish(work, run_id, meta, files, cfg)
    log(run_id, "studio", "published", links["page"], questions=len(items), reels=len(ranges))
    return links


def cast(story: dict) -> dict[str, dict]:
    """Characters by id, each with a distinct valid Hindi speaker."""
    chars, used = {}, set()
    for character in story.get("characters") or []:
        gender = "male" if str(character.get("gender", "")).lower().startswith("m") else "female"
        options = HINDI_SPEAKERS[gender]
        speaker = character.get("speaker")
        if speaker not in options or speaker in used:
            speaker = next((o for o in options if o not in used), options[0])
        used.add(speaker)
        chars[character["id"]] = {**character, "speaker": speaker, "name": character.get("name") or character["id"]}
    return chars


def make_ghar(script_text: str, run_id: str, work: Path, cfg: dict) -> dict:
    story = json.loads(script_text)
    chars = cast(story)
    lines = [line for line in story.get("lines") or [] if line.get("who") in chars and str(line.get("hi") or line.get("text") or "").strip()]
    if len(lines) < 2:
        raise ValueError("a ghar script needs characters and at least 2 lines whose 'who' matches a character id")
    unload_ollama(cfg)

    # the voice reads Devanagari (hi); viewers see Hinglish (text)
    wavs = media.speak_hindi([line.get("hi") or line["text"] for line in lines], [chars[line["who"]]["speaker"] for line in lines], work, cfg)
    seconds = [media.duration(w) for w in wavs]
    cap = float(cfg.get("short_max_seconds", 50)) - 0.5
    if sum(seconds) > cap:
        factor = sum(seconds) / cap
        if factor > 1.2:
            raise ValueError(f"the scene runs {sum(seconds):.0f}s; cut a line or two so it fits {cap:.0f}s")
        seconds = [media.duration(media.tempo(w, factor)) for w in wavs]
    log(run_id, "studio", "audio_ready", f"{len(wavs)} lines", seconds=sum(seconds))

    seed = random.randrange(1 << 30)
    model = cfg.get("realistic_image_model", cfg["image_model"])
    portrait = ("RAW photo, head and shoulders portrait of {look}, facing the camera, looking straight at the camera, "
                "mouth closed, plain indoor wall behind, soft window light, 50mm, sharp focus, realistic skin texture")
    faces = media.paint([portrait.format(look=c.get("look") or c["name"]) for c in chars.values()], REAL_NEGATIVE, work, cfg, seed,
                        size=(512, 640), model=model, prefix="face")
    room = media.paint([f"RAW photo, {story.get('setting') or 'middle-class Indian living room'}, no people, natural light"],
                       REAL_NEGATIVE, work, cfg, seed, size=(512, 768), model=model, prefix="room")[0]
    face_of = dict(zip(chars, faces))
    log(run_id, "studio", "pictures_ready", f"{len(faces)} faces", seed=seed)

    segments = []
    for index, (line, wav, length) in enumerate(zip(lines, wavs, seconds)):
        clip = media.talk(face_of[line["who"]], wav, work / f"talk{index:02d}.mp4", cfg)
        subs = media.card_ass(chars[line["who"]]["name"], line.get("text") or line["hi"], length, work / f"line{index:02d}.ass")
        segments.append(media.card_segment(room, clip, wav, subs, length, work / f"seg{index:02d}.mp4"))
    reel = media.concat(segments, work / "reel.mp4")
    thumb = work / "thumb.jpg"
    media.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(reel), "-frames:v", "1", "-vf", "scale=720:-2", str(thumb)])
    meta = {
        "kind": "ghar",
        "title": story.get("title") or "Ghar ki baat",
        "description": story.get("caption", ""),
        "hashtags": story.get("hashtags", []),
        "script": "\n".join(f"{chars[l['who']]['name']}: {l.get('text') or l['hi']}" for l in lines),
        "run_id": run_id,
    }
    links = publish(work, run_id, meta, {"reel.mp4": reel, "thumb.jpg": thumb}, cfg)
    log(run_id, "studio", "published", links["page"], lines=len(lines))
    return links


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "video"


def publish(work: Path, run_id: str, meta: dict, files: dict[str, Path], cfg: dict) -> dict[str, str]:
    folder = f"{run_id[:8]}-{slugify(meta['title'])}-{run_id[-4:]}"
    dest = Path(cfg["publish_dir"]) / folder
    dest.mkdir(parents=True, exist_ok=True)
    base = cfg["public_url"].rstrip("/") + "/" + folder + "/"
    links = {}
    for name, path in files.items():
        shutil.copy2(path, dest / name)
        links[name] = base + name
    meta = {**meta, "links": links, "page": base}
    (dest / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    videos = "".join(
        f'<figure><video controls preload="metadata" src="{n}"></video>'
        f'<figcaption><a href="{n}" download>Download {html.escape(n)}</a></figcaption></figure>'
        for n in files
        if n.endswith(".mp4")
    )
    (dest / "index.html").write_text(
        f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>{html.escape(meta['title'])}</title><style>{PAGE_CSS}</style>"
        f"<p><a href='../'>&larr; all videos</a></p><h1>{html.escape(meta['title'])}</h1>"
        f"<p>{html.escape(meta.get('description', ''))}<br>{html.escape(' '.join(meta.get('hashtags', [])))}</p>"
        f"<div class=grid>{videos}</div><details><summary>Script</summary><pre>{html.escape(meta['script'])}</pre></details>"
    )
    rebuild_index(Path(cfg["publish_dir"]))
    return {"page": base, **links}


PAGE_CSS = (
    "body{font-family:system-ui;margin:16px;max-width:1200px;background:#111;color:#eee}a{color:#8cf}"
    ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}"
    "video{width:100%;background:#000;border-radius:8px}figure{margin:0}"
)


def rebuild_index(root: Path) -> None:
    rows = []
    for meta_path in sorted(root.glob("*/meta.json"), reverse=True):
        meta = json.loads(meta_path.read_text())
        folder = meta_path.parent.name
        rows.append(
            f"<figure><a href='{folder}/'><img src='{folder}/thumb.jpg' width=100% loading=lazy></a>"
            f"<figcaption><b>{html.escape(meta['kind'])}</b> &middot; <a href='{folder}/'>{html.escape(meta['title'])}</a></figcaption></figure>"
        )
    (root / "index.html").write_text(
        f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>Studio</title>"
        f"<style>{PAGE_CSS}</style><h1>Studio</h1><div class=grid>{''.join(rows)}</div>"
    )


def make(kind_name: str, script_text: str | None, topic: str | None, title: str | None, cfg: dict, draft: bool = False) -> dict:
    kind = KINDS[kind_name]
    run_id = datetime.now().strftime("%Y%m%d%H%M%S") + uuid.uuid4().hex[:4]
    work = Path(cfg["work_dir"]) / run_id
    work.mkdir(parents=True, exist_ok=True)
    log(run_id, "studio", "run_started", kind_name)

    if not script_text:
        if kind["audio"] == "ghar":
            script_text = json.dumps(write_script(kind, topic, cfg, GHAR_SYSTEM), ensure_ascii=False, indent=2)
        elif kind["audio"] == "quiz":
            written = write_script(kind, topic, cfg, QUIZ_SYSTEM)
            items = [(i.get("q", "").strip(), i.get("a", "").strip()) for i in written.get("items") or []]
            script_text = quiz_text(title or written.get("title") or "Quick Quiz", [i for i in items if all(i)][:20])
        else:
            written = write_script(kind, topic, cfg)
            script_text, title = written["script"], title or written.get("title")
    if draft:
        path = Path(cfg["work_dir"]) / "in" / f"{kind_name}-{run_id}.{'json' if kind['audio'] == 'ghar' else 'txt'}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script_text if script_text.endswith("\n") else script_text + "\n")
        log(run_id, "studio", "drafted", str(path))
        return {"draft": str(path)}
    if kind["audio"] == "quiz":
        return make_quiz(kind, script_text, run_id, work, cfg)
    if kind["audio"] == "ghar":
        return make_ghar(script_text, run_id, work, cfg)
    texts = scenes_from(script_text, kind)
    if not texts:
        raise ValueError("the script has no lines")
    plan = ask(cfg, PLAN_SYSTEM, json.dumps({"kind": kind["about"], "title": title or "", "scenes": texts}, ensure_ascii=False))
    unload_ollama(cfg)
    prompts = list(plan.get("images") or [])[: len(texts)]
    prompts += texts[len(prompts) :]  # model returned too few: fall back to the caption itself
    title = title or plan.get("title") or texts[0][:60]
    (work / "plan.json").write_text(json.dumps({"script": script_text, "scenes": texts, "plan": plan}, indent=2, ensure_ascii=False))
    log(run_id, "studio", "planned", title, scenes=len(texts))

    audio, spans = song(script_text, texts, kind, work, cfg) if kind["audio"] == "song" else narrate(texts, kind, work, cfg)
    log(run_id, "studio", "audio_ready", str(audio), seconds=spans[-1][1])

    character = plan.get("character") or ""
    seed = random.randrange(1 << 30)
    images = media.paint(
        [", ".join(p for p in (kind["style"], character, prompt) if p) for prompt in prompts],
        kind["negative"], work, cfg, seed,
    )
    log(run_id, "studio", "pictures_ready", f"{len(images)} images", seed=seed)

    base = media.master(images, spans, audio, work)
    captions = [(a, b, t) for (a, b), t in zip(spans, texts)]
    files = {"full.mp4": media.captioned(base, media.ass(captions, media.FULL, work / "full.ass"), work / "full.mp4")}
    windows = media.short_windows(spans, float(cfg.get("short_max_seconds", 50)), float(cfg.get("short_min_seconds", 12)))
    for number, (first, last) in enumerate(windows, 1):
        start, end = spans[first][0], spans[last][1]
        subs = media.ass(
            [(a - start, b - start, t) for a, b, t in captions[first : last + 1]], media.SHORT, work / f"short{number}.ass"
        )
        files[f"short-{number}.mp4"] = media.vertical_short(base, start, end, subs, work / f"short-{number}.mp4")
    files["thumb.jpg"] = media.thumbnail(images[0], work / "thumb.jpg")

    meta = {
        "kind": kind_name,
        "title": title,
        "description": plan.get("description", ""),
        "hashtags": plan.get("hashtags", []),
        "script": script_text,
        "run_id": run_id,
    }
    links = publish(work, run_id, meta, files, cfg)
    log(run_id, "studio", "published", links["page"], shorts=len(windows))
    return links


def main() -> None:
    parser = argparse.ArgumentParser(description="Make a video and its shorts, publish on the NAS")
    parser.add_argument("kind", choices=sorted(KINDS), help="; ".join(f"{k}: {v['about']}" for k, v in KINDS.items()))
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--script", type=Path, help="your own lyrics or story, used word for word")
    source.add_argument("--topic", help="Ollama writes the script on this topic")
    parser.add_argument("--title")
    parser.add_argument("--draft", action="store_true", help="only write the script to work_dir/in, for you to check and edit")
    args = parser.parse_args()
    cfg = load_config()["studio"]
    links = make(args.kind, args.script.read_text() if args.script else None, args.topic, args.title, cfg, args.draft)
    for name, url in links.items():
        print(f"{name:12} {url}")


if __name__ == "__main__":
    main()
