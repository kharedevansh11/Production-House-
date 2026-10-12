"""Voice, song, pictures, and ffmpeg assembly for studio.py. Every model runs on the NAS."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import httpx

FPS = 30
FULL = (1920, 1080)
SHORT = (1080, 1920)


def run(cmd: list[str]) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if done.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {done.stderr[-1500:]}")
    return done.stdout


def duration(path: Path) -> float:
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]).strip())


# ---------- audio ----------

def speak(text: str, voice: str, speed: float, out: Path, cfg: dict) -> float:
    """Kokoro-FastAPI, OpenAI-compatible. Returns seconds of speech."""
    response = httpx.post(
        cfg["kokoro_url"].rstrip("/") + "/audio/speech",
        json={"model": "kokoro", "input": text, "voice": voice, "speed": speed, "response_format": "wav"},
        timeout=600,
    )
    response.raise_for_status()
    out.write_bytes(response.content)
    return duration(out)


def sing(lyrics: str, style: str, seconds: int, out: Path, cfg: dict) -> Path:
    """ACE-Step 1.5 REST API: submit, poll, download."""
    api = cfg["acestep_url"].rstrip("/")
    submitted = httpx.post(
        api + "/release_task",
        json={
            "prompt": style,
            "lyrics": lyrics,
            "audio_duration": seconds,
            "audio_format": "wav",
            "batch_size": 1,
            "thinking": False,
            "vocal_language": "en",
        },
        timeout=120,
    )
    submitted.raise_for_status()
    task_id = submitted.json()["data"]["task_id"]
    deadline = time.time() + int(cfg.get("song_timeout_seconds", 5400))
    while time.time() < deadline:
        time.sleep(10)
        polled = httpx.post(api + "/query_result", json={"task_id_list": [task_id]}, timeout=60)
        polled.raise_for_status()
        item = polled.json()["data"][0]
        if item["status"] == 2:
            raise RuntimeError(f"ACE-Step failed: {str(item)[:600]}")
        if item["status"] == 1:
            result = json.loads(item["result"]) if isinstance(item["result"], str) else item["result"]
            file_url = (result[0] if isinstance(result, list) else result)["file"]
            audio = httpx.get(api + file_url if file_url.startswith("/") else file_url, timeout=600)
            audio.raise_for_status()
            out.write_bytes(audio.content)
            return out
    raise TimeoutError("ACE-Step did not finish in time")


def vocal_window(song: Path, cfg: dict) -> tuple[float, float]:
    """Where singing starts and ends, so lyric captions skip the intro and outro."""
    total = duration(song)
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(cfg.get("whisper_model", "base"), device="cpu", compute_type="int8")
        segments = list(model.transcribe(str(song), language="en")[0])
    except Exception:  # whisper missing or failed: fall back to the whole track
        segments = []
    if not segments:
        return 0.0, total
    return segments[0].start, min(total, segments[-1].end)


def spread(texts: list[str], start: float, end: float) -> list[tuple[float, float]]:
    """Split [start, end] across lines by text length."""
    # Proportional timing can drift on held notes. Per-word whisper alignment is the next step if captions lag.
    weights = [max(len(t), 1) for t in texts]
    total = sum(weights)
    spans, at = [], start
    for weight in weights:
        step = (end - start) * weight / total
        spans.append((round(at, 3), round(at + step, 3)))
        at += step
    return spans


# ---------- pictures ----------

def paint(prompts: list[str], negative: str, out_dir: Path, cfg: dict, seed: int,
          size: tuple[int, int] = (768, 512), model: str | None = None, prefix: str = "scene") -> list[Path]:
    """Stable Diffusion 1.5 + LCM LoRA: few steps, fits the 4 GB GTX 1050."""
    import torch
    from diffusers import LCMScheduler, StableDiffusionPipeline

    dtype = torch.float16 if cfg.get("image_dtype", "float16") == "float16" else torch.float32
    pipe = StableDiffusionPipeline.from_pretrained(model or cfg["image_model"], torch_dtype=dtype)
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
    pipe.load_lora_weights(cfg["image_lora"])
    pipe.fuse_lora()
    pipe.enable_attention_slicing()
    pipe.enable_model_cpu_offload()
    paths = []
    for index, prompt in enumerate(prompts):
        path = out_dir / f"{prefix}{index:02d}.png"
        pipe(
            prompt,
            negative_prompt=negative,
            width=size[0],
            height=size[1],
            num_inference_steps=int(cfg.get("image_steps", 6)),
            guidance_scale=1.5,
            generator=torch.Generator("cpu").manual_seed(seed + index),
        ).images[0].save(path)
        paths.append(path)
    del pipe
    torch.cuda.empty_cache()
    return paths


# ---------- assembly ----------

def ass_time(seconds: float) -> str:
    centis = int(round(seconds * 100))
    return f"{centis // 360000}:{centis // 6000 % 60:02d}:{centis // 100 % 60:02d}.{centis % 100:02d}"


def ass(lines: list[tuple[float, float, str]], size: tuple[int, int], out: Path) -> Path:
    width, height = size
    font = 64 if width > height else 72
    margin = 70 if width > height else 520
    events = []
    for a, b, text in lines:
        if b > a:
            safe = text.replace("{", "(").replace("}", ")").replace("\n", r"\N")
            events.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Main,,0,0,0,,{safe}")
    body = "\n".join(events)
    out.write_text(
        f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,DejaVu Sans,{font},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{body}
"""
    )
    return out


def scene_clip(image: Path, seconds: float, zoom_in: bool, out: Path) -> Path:
    """Ken Burns on one still. Upscale first so zoompan does not jitter."""
    frames = max(1, int(round(seconds * FPS)))
    zoom = "min(1.0+0.12*on/{n},1.12)" if zoom_in else "max(1.12-0.12*on/{n},1.0)"
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(image),
            "-vf",
            f"scale=2880:1620:force_original_aspect_ratio=increase,crop=2880:1620,"
            f"zoompan=z='{zoom.format(n=frames)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={FULL[0]}x{FULL[1]}:fps={FPS}",
            "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out),
        ]
    )
    return out


def master(images: list[Path], spans: list[tuple[float, float]], audio: Path, work: Path) -> Path:
    """One clip per scene, back to back, under the full audio. No captions yet."""
    clips = []
    for index, (image, (start, end)) in enumerate(zip(images, spans)):
        clips.append(scene_clip(image, end - start, index % 2 == 0, work / f"clip{index:02d}.mp4"))
    listing = work / "clips.txt"
    listing.write_text("".join(f"file '{clip.name}'\n" for clip in clips))
    out = work / "master.mp4"
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
            "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(out),
        ]
    )
    return out


def captioned(source: Path, subs: Path, out: Path) -> Path:
    _run_in(
        subs.parent,
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(source.resolve()), "-vf", f"subtitles={subs.name}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy", str(out.resolve()),
        ],
    )
    return out


def _run_in(cwd: Path, cmd: list[str]) -> str:
    # subtitles= parses ':' and '\' in paths, so run beside the .ass and pass a bare name
    done = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    if done.returncode:
        raise RuntimeError(f"{cmd[0]} failed: {done.stderr[-1500:]}")
    return done.stdout


def short_windows(spans: list[tuple[float, float]], max_seconds: float, min_seconds: float) -> list[tuple[int, int]]:
    """Group consecutive scenes into vertical shorts no longer than max_seconds."""
    windows, first = [], 0
    for index in range(len(spans)):
        too_long = spans[index][1] - spans[first][0] > max_seconds
        if too_long and index > first:
            windows.append((first, index - 1))
            first = index
    windows.append((first, len(spans) - 1))
    # a short tail is merged backwards unless that would break the cap
    if len(windows) > 1:
        a, b = windows[-2], windows[-1]
        if spans[b[1]][1] - spans[b[0]][0] < min_seconds and spans[b[1]][1] - spans[a[0]][0] <= max_seconds:
            windows[-2:] = [(a[0], b[1])]
    return windows


def vertical_short(source: Path, start: float, end: float, subs: Path, out: Path) -> Path:
    """Landscape scene centred on a blurred copy of itself, captions in the lower third."""
    graph = (
        f"[0:v]split[a][b];"
        f"[a]scale={SHORT[0]}:{SHORT[1]}:force_original_aspect_ratio=increase,crop={SHORT[0]}:{SHORT[1]},boxblur=30:3[bg];"
        f"[b]scale={SHORT[0]}:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2-160,subtitles={subs.name}"
    )
    _run_in(
        subs.parent,
        [
            "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source.resolve()),
            "-filter_complex", graph, "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-c:a", "aac", "-b:a", "160k", str(out.resolve()),
        ],
    )
    return out


def thumbnail(image: Path, out: Path) -> Path:
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(image), "-vf", "scale=1280:-2", str(out)])
    return out


# ---------- rapid-fire quiz ----------

def tone(out: Path, seconds: float, freq: int = 0) -> Path:
    """Silence (freq=0) or a short ding, in Kokoro's format (24 kHz mono)."""
    source = f"sine=f={freq}:d={seconds}" if freq else f"anullsrc=r=24000:cl=mono:d={seconds}"
    fade = f",afade=t=out:st=0.04:d={seconds - 0.04},volume=0.6" if freq else ""
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", source, "-af", f"aresample=24000{fade}", "-ac", "1", "-c:a", "pcm_s16le", str(out)])
    return out


def join_audio(parts: list[Path], out: Path) -> Path:
    inputs = [arg for part in parts for arg in ("-i", str(part))]
    graph = "".join(f"[{i}:a]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[a]"
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", graph, "-map", "[a]", "-ac", "1", "-ar", "24000", str(out)])
    return out


# ASS colours are &HAABBGGRR
GREY, YELLOW, GREEN, GOLD = "&H00503A2E&", "&H003CC9FF&", "&H0071CC2E&", "&H0000D7FF&"


def quiz_ass(title: str, items: list[tuple[str, str]], timings: list[tuple[float, float, float]],
             intro_end: float, outro: str, total: float, out: Path, first_number: int = 1) -> Path:
    """Title, current question, revealed answer, and a grid of numbered boxes that tick green."""
    width, height = SHORT
    events = []

    def add(start: float, end: float, text: str, layer: int = 1) -> None:
        if end > start:
            events.append(f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},Q,,0,0,0,,{text}")

    def clean(text: str) -> str:
        return text.replace("{", "(").replace("}", ")").replace("\n", " ")

    cols, gap, left, top, bottom = 4, 18, 60, 1000, 1840
    rows = -(-len(items) // cols)
    box_w = (width - 2 * left - (cols - 1) * gap) / cols
    box_h = (bottom - top - (rows - 1) * gap) / rows

    add(0, total, rf"{{\an8\pos(540,110)\fs78\1c{GOLD}}}{clean(title)}")
    add(0, intro_end, rf"{{\an5\pos(540,560)\fs80}}How many can you get right?")
    last_end = timings[-1][2] if timings else intro_end
    add(last_end, total, rf"{{\an5\pos(540,560)\fs80}}{clean(outro)}")
    for index, ((question, answer), (asked, revealed, done)) in enumerate(zip(items, timings)):
        x = left + (index % cols) * (box_w + gap)
        y = top + (index // cols) * (box_h + gap)
        cx, cy = x + box_w / 2, y + box_h / 2
        shape = f"m 0 0 l {box_w:.0f} 0 l {box_w:.0f} {box_h:.0f} l 0 {box_h:.0f}"

        def box(fill: str) -> str:
            return rf"{{\an7\pos({x:.0f},{y:.0f})\p1\bord4\shad0\1c{fill}\3c&H00FFFFFF&}}{shape}{{\p0}}"

        add(0, asked, box(GREY), 0)
        add(0, asked, rf"{{\an5\pos({cx:.0f},{cy:.0f})\fs56}}{index + first_number}")
        add(asked, revealed, box(YELLOW), 0)
        add(asked, revealed, rf"{{\an5\pos({cx:.0f},{cy:.0f})\fs56\1c&H00000000&\bord0}}{index + first_number}")
        add(revealed, total, box(GREEN), 0)
        short = clean(answer) if len(answer) <= 14 else clean(answer)[:13] + "…"
        add(revealed, total, rf"{{\an5\pos({cx:.0f},{cy:.0f})\fs36}}✓\N{short}")
        add(asked, done, rf"{{\an5\pos(540,450)\fs64}}Q{index + first_number}. {clean(question)}")
        add(revealed, done, rf"{{\an5\pos(540,760)\fs100\1c&H005CE65C&\bord6}}{clean(answer)}")

    out.write_text(
        f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Q,DejaVu Sans,60,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,5,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        + "\n".join(events)
        + "\n"
    )
    return out


def quiz_video(subs: Path, audio: Path, out: Path, background: str = "0x1b1f3b") -> Path:
    _run_in(
        subs.parent,
        [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={background}:s={SHORT[0]}x{SHORT[1]}:r={FPS}",
            "-i", str(audio.resolve()), "-vf", f"subtitles={subs.name}", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out.resolve()),
        ],
    )
    return out


# ---------- Hindi household reels ----------

def speak_hindi(texts: list[str], speakers: list[str], out_dir: Path, cfg: dict) -> list[Path]:
    """Indic Parler-TTS (AI4Bharat). Hindi speakers: Divya, Rani (female), Rohit, Aman (male)."""
    import soundfile
    import torch
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    name = cfg.get("hindi_tts_model", "ai4bharat/indic-parler-tts")
    device = cfg.get("hindi_tts_device", "cpu")
    model = ParlerTTSForConditionalGeneration.from_pretrained(name).to(device)
    tokenizer = AutoTokenizer.from_pretrained(name)
    describe = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
    paths = []
    for index, (text, speaker) in enumerate(zip(texts, speakers)):
        description = describe(
            f"{speaker} speaks at a moderate pace with an expressive, natural tone. "
            "Very clear audio, close-sounding recording, no background noise.",
            return_tensors="pt",
        ).to(device)
        prompt = tokenizer(text, return_tensors="pt").to(device)
        torch.manual_seed(index)
        audio = model.generate(
            input_ids=description.input_ids,
            attention_mask=description.attention_mask,
            prompt_input_ids=prompt.input_ids,
            prompt_attention_mask=prompt.attention_mask,
        )
        path = out_dir / f"line{index:02d}.wav"
        soundfile.write(str(path), audio.cpu().numpy().squeeze(), model.config.sampling_rate)
        paths.append(path)
    del model
    return paths


def tempo(path: Path, factor: float) -> Path:
    """Speed speech up by factor (pitch kept), in place."""
    sped = path.with_suffix(".fast.wav")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-filter:a", f"atempo={factor:.3f}", str(sped)])
    sped.replace(path)
    return path


def talk(face: Path, audio: Path, out: Path, cfg: dict) -> Path:
    """SadTalker service: a still portrait plus speech becomes a talking-head clip. Paths are shared via /work."""
    response = httpx.post(
        cfg["sadtalker_url"].rstrip("/") + "/talk",
        json={"image": str(face), "audio": str(audio), "out": str(out)},
        timeout=float(cfg.get("sadtalker_timeout_seconds", 3600)),
    )
    response.raise_for_status()
    if not out.is_file():
        raise RuntimeError(f"SadTalker returned no video: {response.text[:400]}")
    return out


def card_ass(name: str, text: str, seconds: float, out: Path) -> Path:
    width, height = SHORT

    def clean(value: str) -> str:
        return value.replace("{", "(").replace("}", ")").replace("\n", " ")

    out.write_text(
        f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Line,DejaVu Sans,68,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,5,0,2,70,70,300,1
Style: Name,DejaVu Sans,58,{GOLD},&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,3,14,0,8,70,70,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,{ass_time(0)},{ass_time(seconds)},Name,,0,0,0,,{clean(name)}
Dialogue: 0,{ass_time(0)},{ass_time(seconds)},Line,,0,0,0,,{clean(text)}
"""
    )
    return out


def card_segment(background: Path, clip: Path, audio: Path, subs: Path, seconds: float, out: Path) -> Path:
    """One spoken line: blurred room behind, the talking face in front, name on top, Hinglish caption below."""
    graph = (
        f"[0:v]scale={SHORT[0]}:{SHORT[1]}:force_original_aspect_ratio=increase,crop={SHORT[0]}:{SHORT[1]},"
        f"boxblur=6:1,eq=brightness=-0.10[bg];"
        f"[1:v]scale=920:-2,setsar=1[fg];"
        f"[bg][fg]overlay=(W-w)/2:250,fps={FPS},subtitles={subs.name},format=yuv420p[v]"
    )
    _run_in(
        subs.parent,
        [
            "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(background.resolve()), "-i", str(clip.resolve()),
            "-i", str(audio.resolve()), "-filter_complex", graph, "-map", "[v]", "-map", "2:a", "-t", f"{seconds:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k",
            str(out.resolve()),
        ],
    )
    return out


def concat(segments: list[Path], out: Path) -> Path:
    """Segments were encoded with identical settings, so they join without re-encoding."""
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{segment.resolve()}'\n" for segment in segments))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])
    return out
