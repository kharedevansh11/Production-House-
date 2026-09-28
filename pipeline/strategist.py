"""Slide 1–3: public-text research, an original script, and a winning hook.

This role never downloads Instagram, TikTok, or YouTube videos.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from config_loader import DATA
from llm import complete, parse_json_object

ANGLES_SYSTEM = """You plan original short-form videos.
Return JSON only: {"angles":[{"topic":"","visual_style":"","why":""}]}.
Write exactly 5 angles. They must be new scripts for the niche, not copies of posts you were shown.
visual_style describes an original on-screen treatment (text, chat, diagram), not a downloaded video.
"""

SCRIPT_SYSTEM = """You write one high-retention short script.
Return JSON only: {"hook":"","lines":[""],"cta":"","caption":"","hashtags":["#tag"],"duration_seconds":24}.
The hook is a pattern interrupt that can be spoken in the first 2 seconds.
lines are the spoken beats after the hook, then the payoff. 3 to 5 lines.
cta is a soft call to action, one sentence.
The whole script, spoken aloud, lasts between 20 and 30 seconds.
caption is the post caption. hashtags is 3 to 5 tags.
Do not quote or retell a specific third-party video.
"""

HOOKS_SYSTEM = """You write original hook lines.
Return JSON only: {"hooks":[{"line":"","trigger":"surprise|curiosity|desire|ego|fear","score":8}],"winner":""}.
Write exactly 5 hooks for the script. winner is the line with the highest score and must match one hook line exactly.
Each hook creates a pattern interrupt in the first 2 seconds. Do not copy a hook from an existing Reel.
"""


def reddit_snippets(niche: str, limit: int = 12) -> list[str]:
    """Titles from Reddit's public search. No video files."""
    response = httpx.get(
        "https://www.reddit.com/search.json",
        params={"q": niche, "sort": "top", "t": "month", "limit": str(limit), "type": "link"},
        headers={"User-Agent": "openshorts-pipeline/1.0"},
        timeout=20,
    )
    response.raise_for_status()
    children = response.json().get("data", {}).get("children", [])
    snippets = []
    for child in children:
        data = child.get("data") or {}
        title = (data.get("title") or "").strip()
        if title:
            snippets.append(title)
    return snippets


def _ask(config: dict, system: str, user: str, complete_fn) -> dict:
    ollama = config["ollama"]
    text = complete_fn(ollama["base_url"], ollama["model"], system, user)
    return parse_json_object(text)


def research(config: dict, search_fn=reddit_snippets, complete_fn=complete) -> dict:
    niche = config["niche"].strip()
    try:
        snippets = search_fn(niche)
        search_note = f"{len(snippets)} reddit titles"
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
        snippets = []
        search_note = f"search unavailable ({exc.__class__.__name__})"
    shown = "\n".join(f"- {title}" for title in snippets[:12]) or "- (no public titles; invent from the niche alone)"
    angles = _ask(
        config,
        ANGLES_SYSTEM,
        f"Niche: {niche}\nPublic titles from the last 30 days, for pattern only:\n{shown}\n"
        "Give the 5 highest-demand original angles.",
        complete_fn,
    )
    if len(angles.get("angles") or []) < 5:
        raise ValueError("strategist returned fewer than 5 angles")
    angle = angles["angles"][0]
    script = _ask(
        config,
        SCRIPT_SYSTEM,
        json.dumps({"niche": niche, "angle": angle}, ensure_ascii=False),
        complete_fn,
    )
    low = int(config["script"]["min_seconds"])
    high = int(config["script"]["max_seconds"])
    duration = int(script.get("duration_seconds") or 24)
    script["duration_seconds"] = max(low, min(high, duration))
    hooks = _ask(
        config,
        HOOKS_SYSTEM,
        json.dumps({"niche": niche, "angle": angle, "script": script}, ensure_ascii=False),
        complete_fn,
    )
    hook_lines = [item.get("line", "").strip() for item in hooks.get("hooks") or []]
    if len(hook_lines) < 5:
        raise ValueError("strategist returned fewer than 5 hooks")
    winner = (hooks.get("winner") or "").strip()
    if winner not in hook_lines:
        winner = max(hooks["hooks"], key=lambda item: int(item.get("score") or 0))["line"].strip()
    script["hook"] = winner
    lines = [line.strip() for line in script.get("lines") or [] if str(line).strip()]
    script["lines"] = lines
    script["cta"] = str(script.get("cta") or "").strip()
    brief = {
        "niche": niche,
        "search": search_note,
        "angles": angles["angles"][:5],
        "chosen_angle": angle,
        "hooks": hooks["hooks"][:5],
        "hook": winner,
        "script": script,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "angles.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False) + "\n")
    return brief


def spoken_lines(brief: dict) -> list[str]:
    script = brief["script"]
    lines = [brief["hook"]]
    lines.extend(script.get("lines") or [])
    cta = script.get("cta") or ""
    if cta and cta not in lines:
        lines.append(cta)
    return [line for line in lines if line]
