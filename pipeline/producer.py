"""Render the strategist's script with Hypit's local chat-scene template.

No generation-model imports. No reference video.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from html import escape
from pathlib import Path

from config_loader import DATA, HYPIT_REPO, TEMPLATE
from strategist import spoken_lines

FORBIDDEN_IMPORTS = (
    "seedance",
    "nano-banana",
    "gpt-image",
    "kling",
    "veo",
    "fal.ai",
    "elevenlabs",
)


def write_svml(brief: dict, destination: Path, config: dict) -> str:
    lines = spoken_lines(brief)
    if not lines:
        raise ValueError("script has no lines")
    duration = int(brief["script"]["duration_seconds"])
    width = int(config["hypit"]["canvas_width"])
    height = int(config["hypit"]["canvas_height"])
    # Keep the last line inside the timeline and at least ~2s apart.
    slots = max(len(lines) - 1, 1)
    gap = max(2.0, (duration - 2) / slots)
    messages = []
    for index, text in enumerate(lines):
        at = min(duration - 1, round(0.4 + index * gap, 2))
        side = "left" if index % 2 == 0 else "right"
        sender = "Hook" if index == 0 else ("CTA" if index == len(lines) - 1 else "Beat")
        messages.append(
            f'    <chat:Message id="line{index}" sender="{escape(sender)}" side="{side}" '
            f'at="{at}s" text="{escape(text, quote=True)}"/>'
        )
    title = escape(str(brief["chosen_angle"].get("topic") or brief["niche"])[:48], quote=True)
    svml = f"""<?svml using="@hypit/markup@1"?>
<svml>
  <import as="time" from="@hypit/timeline-author@1"/>
  <import as="spatial" from="@hypit/spatial@1"/>
  <import as="fonts" from="@hypit/fonts-open@1"/>
  <import as="chat" from="@example/chat-scene@1"/>
  <import as="film" from="@hypit/film@1"/>
  <import as="render" from="@hypit/render-hyperframes@1"/>
  <import as="style" source="./reel.svs"/>

  <time:Clock id="animation-clock" frame-rate="30"/>
  <time:Timeline id="animation" clock={{animation-clock}} end="{duration}s"/>
  <spatial:Canvas id="canvas" width="{width}" height="{height}"/>
  <fonts:Stack id="font" family="inter" weight="600" style="normal"/>
  <chat:Scene id="conversation" timeline={{animation.timeline}} canvas={{canvas}} font={{font}}
    during="program" title="{title}">
{chr(10).join(messages)}
  </chat:Scene>
  <film:Film id="main" canvas={{canvas}} timeline={{animation.timeline}} appearance={{style.film.main}}>
    <film:Track source={{conversation.track}}/>
  </film:Film>
  <render:Video id="final" composition={{main.composition}} timeline={{animation.timeline}}/>
</svml>
"""
    lowered = svml.lower()
    for token in FORBIDDEN_IMPORTS:
        if token in lowered:
            raise ValueError(f"refusing to render a generation-model import: {token}")
    if escape(brief["hook"], quote=True) not in svml:
        raise ValueError("svml is missing the winning hook")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(svml)
    return svml


def _json_objects(text: str) -> list[dict]:
    found = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(obj, dict):
            found.append(obj)
        index = end
    return found


def _build_id(payload: dict) -> str | None:
    build = payload.get("build")
    if isinstance(build, dict) and isinstance(build.get("id"), str):
        return build["id"]
    if isinstance(payload.get("id"), str) and payload.get("format") == "hypit.cli-build@1":
        return payload["id"]
    for value in payload.values():
        if isinstance(value, dict):
            found = _build_id(value)
            if found:
                return found
    return None


def render(brief: dict, run_id: str, config: dict) -> dict:
    if config["hypit"].get("generation_models"):
        raise ValueError("generation models are disabled for this pipeline")
    run_dir = DATA / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    svml_path = TEMPLATE / "reel.svml"
    svml = write_svml(brief, svml_path, config)
    (run_dir / "reel.svml").write_text(svml)
    (run_dir / "brief.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False) + "\n")

    launcher = HYPIT_REPO / "bin" / "hypit.mjs"
    package_dist = TEMPLATE / "packages" / "chat-scene" / "dist" / "activation.js"
    if not launcher.is_file():
        raise FileNotFoundError(f"Hypit launcher missing at {launcher}. Run pnpm install in {HYPIT_REPO}.")
    if not package_dist.is_file():
        raise FileNotFoundError(
            "Hypit chat-scene is not built. From the hypit checkout run: "
            "pnpm install --frozen-lockfile && pnpm build:public-types && "
            "pnpm --filter @example/chat-scene build"
        )
    runtime = TEMPLATE / "hypit.runtime.json"
    command = [
        "node",
        str(launcher),
        "build",
        "reel.svrun",
        "--workspace",
        str(TEMPLATE),
        "--runtime",
        str(runtime),
        "--follow",
        "--json",
        "--title",
        run_id,
    ]
    completed = subprocess.run(
        command,
        cwd=str(HYPIT_REPO),
        capture_output=True,
        text=True,
        timeout=7200,
        check=False,
    )
    (run_dir / "hypit-build.log").write_text(completed.stdout + "\n" + completed.stderr)
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout)[-1200:]
        raise RuntimeError(f"hypit build failed: {tail}")
    build_id = None
    for obj in _json_objects(completed.stdout):
        build_id = _build_id(obj) or build_id
    if not build_id:
        raise RuntimeError("hypit build finished without a build id")
    ready = DATA / "ready"
    ready.mkdir(parents=True, exist_ok=True)
    destination = ready / f"{run_id}.mp4"
    export = subprocess.run(
        [
            "node",
            str(launcher),
            "get",
            build_id,
            "--output",
            "final.video",
            "--to",
            str(destination),
            "--workspace",
            str(TEMPLATE),
            "--json",
        ],
        cwd=str(HYPIT_REPO),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    (run_dir / "hypit-get.log").write_text(export.stdout + "\n" + export.stderr)
    if export.returncode != 0 or not destination.is_file():
        copied = _copy_rendered_video(destination)
        if not copied:
            tail = (export.stderr or export.stdout)[-1200:]
            raise RuntimeError(f"hypit get failed: {tail}")
    return {
        "video": str(destination),
        "build_id": build_id,
        "hook": brief["hook"],
        "duration_seconds": int(brief["script"]["duration_seconds"]),
        "template": "hypit-chat-scene",
    }


def _copy_rendered_video(destination: Path) -> bool:
    """Fallback if `hypit get` cannot see the output but the runtime wrote an mp4."""
    runtime_root = TEMPLATE / ".hypit" / "runtimes" / "local"
    if not runtime_root.is_dir():
        return False
    candidates = sorted(runtime_root.rglob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return False
    shutil.copy2(candidates[0], destination)
    return destination.is_file() and destination.stat().st_size > 0
