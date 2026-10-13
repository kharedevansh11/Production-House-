# Openshots

A local daily loop that writes one original 20–30 second vertical short, and a separate command that clips a long video you already own.

[Hypit](https://github.com/hypit-ai/hypit) renders the daily short from a local chat-scene template: on-screen captions and layout. [OpenShorts](https://github.com/mutonby/openshorts) is only the clipper. [Ollama](https://ollama.com) writes the script. No Gemini key.

The daily pass does not search YouTube, Instagram, or TikTok for videos to download. It reads public Reddit titles for the niche, then writes a new script.

This repository is the pipeline. Hypit and OpenShorts stay separate clones. Their licenses are theirs.

## What a run does

`pipeline/orchestrator.py` does one pass:

1. **Strategist.** Reads public Reddit titles for the niche (text only). Asks Ollama for 5 original angles, one 20–30 second script, and 5 hooks. The highest-scoring hook becomes the first spoken line.
2. **Producer.** Renders that script with Hypit’s local chat-scene template to `pipeline/data/ready/<run-id>.mp4`. Seedance, image models, and reference Reels stay off.
3. **Reviewer.** Holds the file if the opening line is not that hook, the file is missing, the length is outside 20–30 seconds, or 3 videos are already scheduled today.
4. **Publisher.** After a pass, schedules the same file to TikTok, Instagram, and YouTube through [Upload-Post](https://app.upload-post.com/manage-users), inside 08:00–22:00 in the timezone in `pipeline/config.yaml`. Facebook is not posted. A fourth video that day is held.

`pipeline/assistant.py` answers questions about the supervisor log. It cannot render or publish.

Clipping is a different command, `pipeline/openshorts_clip.py`. It runs only when the source is on the allowlist in `pipeline/config.yaml`. A YouTube link that is not on that list is refused.

## Layout

Clone the three projects side by side:

```text
Openshots/          this repo
openshorts/         clone of OpenShorts
hypit/              clone of Hypit, pinned below
```

The pipeline expects that layout. `pipeline/config_loader.py` looks for `../hypit`.

## Requirements

- Docker, for OpenShorts
- Python 3.11
- Node.js 22.15 or newer, and pnpm 10.33
- Ollama
- FFmpeg (`ffprobe` on the PATH), so the reviewer can measure the file
- 16 GB RAM. Use `qwen2.5:14b` only if the machine has 32 GB, and set `ollama.model` in `pipeline/config.yaml` to match
- A GPU is optional

Upload-Post’s free tier is 10 uploads a month. Three videos a day, each sent to three platforms, needs their paid plan.

## 1. Ollama

```bash
OLLAMA_CONTEXT_LENGTH=16384 ollama serve
ollama pull qwen2.5:7b
```

Leave that server running. The pipeline talks to `http://127.0.0.1:11434/v1`.

## 2. OpenShorts

```bash
git clone https://github.com/mutonby/openshorts.git openshorts
cd openshorts
cp .env.example .env
```

In `openshorts/.env`, set:

```bash
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_MODEL=qwen2.5:7b
```

Leave Gemini, ElevenLabs, fal.ai, S3, and billing unset. Frame-based OpenShorts stages still expect Gemini when you use them; the transcript moment picker uses the local model.

So the container can reach Ollama on the host, add `openshorts/docker-compose.override.yml`:

```yaml
services:
  backend:
    env_file:
      - .env
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Start it:

```bash
docker compose up --build -d
```

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:5175 |
| API | http://localhost:8000 |
| Remotion renderer | http://localhost:3100 |

OpenShorts core is MIT. Everything under `openshorts/cloud/` is under the commercial license in that directory, not MIT. This pipeline does not use the cloud app.

## 3. Hypit

From the parent of this repo (the directory that contains `pipeline/`):

```bash
git clone https://github.com/hypit-ai/hypit.git hypit
cd hypit
git checkout b00532e413d8
pnpm install --frozen-lockfile
pnpm build:public-types
pnpm --filter @example/chat-scene build
```

Hypit is Apache-2.0 with extra conditions. Running it on your own machine for your own videos is allowed. Offering Hypit as a hosted multi-tenant service is not. Do not remove Hypit’s name or copyright from its CLI output. See [Hypit’s license](https://github.com/hypit-ai/hypit/blob/main/LICENSE).

## 4. Pipeline

```bash
cd pipeline
cp .env.example .env
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Edit `pipeline/config.yaml`:

- Replace `REPLACE_WITH_YOUR_NICHE` with the niche. The run refuses to start while that placeholder is still there.
- Set `timezone` if you are not in `Asia/Kolkata`. Posts are scheduled in that zone, between `day_start_hour` and `day_end_hour`.
- To clip a video you own, add it under `openshorts.allowlist`: a channel id, an `@handle`, an exact URL, or a local directory.

Edit `pipeline/.env` and set `UPLOAD_POST_API_KEY`. In Upload-Post, create a profile named `default` (or set `UPLOAD_POST_PROFILE`) and connect TikTok, Instagram, and YouTube.

One pass:

```bash
cd pipeline
.venv/bin/python orchestrator.py
```

The finished file, when the reviewer passes it, is `pipeline/data/ready/<run-id>.mp4`.

Ask about the log:

```bash
.venv/bin/python assistant.py "what was held today?"
```

Clip one video you own, after it is on the allowlist:

```bash
.venv/bin/python openshorts_clip.py "/path/you/own/video.mp4"
```

OpenShorts still asks for a rights acknowledgement. This command sends it only after the allowlist check.

## Daily timer

After one manual pass writes a file under `pipeline/data/ready/`, a systemd oneshot can run the same command once a day:

```ini
[Service]
WorkingDirectory=/path/to/Openshots/pipeline
ExecStart=/path/to/Openshots/pipeline/.venv/bin/python orchestrator.py
```

Leave the timer off until that manual pass succeeds.

## Studio: full videos, reels, and Hindi household reels on the NAS

`pipeline/studio.py` is a separate command that runs entirely on a home server. It makes Hindi household reels (AI family portraits, Hindi voices, Hinglish captions), rapid-fire quiz reels, did-you-know facts, creepy stories, and sung nursery rhymes. Every reel is 50 seconds or less, and finished videos are served on the LAN for watching or downloading. It needs no Hypit, no OpenShorts, and no API keys. Setup and commands: [pipeline/studio/README.md](pipeline/studio/README.md).

## License

The pipeline in this repository is MIT. See [LICENSE](LICENSE).

`pipeline/template/packages/chat-scene/` is Hypit’s chat-scene example. It stays under [Hypit’s license](https://github.com/hypit-ai/hypit/blob/main/LICENSE), not the MIT grant above. See [pipeline/template/NOTICE.md](pipeline/template/NOTICE.md).

OpenShorts core is MIT, with the `cloud/` exception noted above. This project does not claim authorship of Hypit or OpenShorts.
