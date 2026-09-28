# Local shorts pipeline

Hypit renders original 20–30 second shorts. OpenShorts is only for clipping a long video you already own. The daily timer does not search YouTube, Instagram, or TikTok for videos to download.

## What you set once

1. Open `pipeline/config.yaml` and replace `REPLACE_WITH_YOUR_NICHE` with the niche for the carousel. That string is the `[niche]` placeholder.
2. Copy `pipeline/.env.example` to `pipeline/.env` and set `UPLOAD_POST_API_KEY`.
3. In [Upload-Post](https://app.upload-post.com/manage-users), create a profile (the default name in config is `default`) and connect TikTok, Instagram, and YouTube. Facebook is not posted by this pipeline.
4. On the Linux box, install Docker, Node.js, pnpm, and [Ollama](https://ollama.com). 16 GB RAM is the minimum.

Three videos a day are each scheduled to TikTok, Instagram, and YouTube, inside 08:00–22:00 in the timezone in `config.yaml` (`Asia/Kolkata` unless you change it). A fourth video the same day is held. Upload-Post's free tier is 10 uploads a month, so this pace needs their paid plan.

## Ollama

The strategist uses a local model. No Gemini key.

```bash
OLLAMA_CONTEXT_LENGTH=16384 ollama serve
ollama pull qwen2.5:7b
```

Use `qwen2.5:14b` only if the machine has 32 GB, and set `ollama.model` in `config.yaml` to match. OpenShorts reads the same model through `openshorts/.env` (`LLM_BASE_URL=http://host.docker.internal:11434/v1`).

## OpenShorts (owned long videos only)

```bash
cd openshorts
docker compose up --build -d
```

Dashboard: `http://<linux-ip>:5175`. The backend is on port 8000. `docker-compose.override.yml` points the container at Ollama on the host. Billing, S3, Gemini, fal.ai, and ElevenLabs are unset.

To clip one video you own, add it to `openshorts.allowlist` in `config.yaml` (a channel id, a `@handle`, an exact URL, or a local directory). Then:

```bash
cd pipeline
.venv/bin/python openshorts_clip.py "/path/you/own/video.mp4"
```

A YouTube link that is not on that list is refused. OpenShorts still requires the rights acknowledgement, and this command sends it only after the allowlist check.

## Hypit (the daily video)

The render is the local chat-scene template: captions and layout, no Seedance, no image model, no reference Reel. Their examples that call those models cost about $1; this path does not.

One-time build, from the repo root:

```bash
cd hypit
pnpm install --frozen-lockfile
pnpm build:public-types
pnpm --filter @example/chat-scene build
```

Python side:

```bash
cd pipeline
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

One pass (research, script, hook, local render, review, schedule):

```bash
cd pipeline
.venv/bin/python orchestrator.py
```

The strategist reads public Reddit titles for the niche, then writes 5 original angles, one 20–30 second script, and 5 hooks. The winning hook is the first line. Hypit writes `pipeline/data/ready/<run-id>.mp4`. The reviewer holds the file if the hook does not match, the length is outside 20–30 seconds, or 3 videos are already scheduled today.

Ask the assistant about the log. It cannot render or publish.

```bash
cd pipeline
.venv/bin/python assistant.py "what was held today?"
```

The supervisor is the only writer of `pipeline/data/supervisor.jsonl`.

## Daily timer

After one manual pass produces a file under `pipeline/data/ready/`:

```ini
[Service]
WorkingDirectory=/path/to/Openshots/pipeline
ExecStart=/path/to/Openshots/pipeline/.venv/bin/python orchestrator.py
```

Run that service once a day. Leave it off until the manual pass succeeds.
