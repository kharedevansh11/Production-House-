# Openshots

Openshots is a local pipeline that makes one original short video a day, and can separately clip a long video the operator already owns.

Two other open-source projects do the heavy work. Hypit renders the daily short. OpenShorts clips the owned long video. Ollama, running on the same machine, writes the script. There is no Gemini API key.

The daily pass does not search YouTube, Instagram, or TikTok, and it does not download videos from those sites. Research is public Reddit post titles only. The script is new.

## The two engines

Hypit is the renderer for the daily video. The pipeline uses Hypit’s local chat-scene template. The picture is captions and a chat layout on a 1080 by 1920 vertical canvas. The spoken lines are the hook, then three to five beats, then a short call to action. Seedance, image-generation models, and a reference Reel are turned off. Hypit examples that call those paid models cost about one dollar. This path does not call them.

OpenShorts is the clipper, and only the clipper. It is the open-source project at github.com/mutonby/openshorts. The operator runs it with Docker on their own machine. The dashboard is http://localhost:5175. The API is port 8000. A Remotion renderer listens on port 3100. The pipeline points OpenShorts at the same local Ollama model, so the transcript moment picker does not need Gemini. Frame-based OpenShorts features still expect a Gemini key if someone turns them on. This pipeline leaves Gemini, ElevenLabs, fal.ai, S3, and billing unset.

OpenShorts core is MIT. The cloud directory inside OpenShorts is commercial software under its own license. Openshots does not run that cloud product, and it is not OpenShorts Cloud.

## The model

The writing model is Ollama’s qwen2.5:7b, served at http://127.0.0.1:11434/v1. Ollama must be started with a context length of 16384, because the default of 4096 is too small. qwen2.5:14b is only for a machine with 32 GB of RAM, and the config must name that model. 16 GB of RAM is the minimum. A GPU is optional. Docker reaches Ollama on the host through host.docker.internal.

## One daily pass

The command is pipeline/orchestrator.py. It refuses to start until the niche in pipeline/config.yaml is no longer the placeholder REPLACE_WITH_YOUR_NICHE. One pass has four roles and a log.

The strategist reads up to 12 public Reddit titles from the last month for that niche. Titles are text. If Reddit is unreachable, it continues from the niche alone. It then asks Ollama for exactly 5 original angles. Each angle has a topic, an on-screen treatment, and a reason. The treatment is text, chat, or a diagram, not a downloaded video. It picks the first angle and asks for one script: a hook that can be spoken in the first 2 seconds, 3 to 5 spoken lines, one soft call to action, a caption, 3 to 5 hashtags, and a duration between 20 and 30 seconds. It then asks for exactly 5 hooks. Each hook is scored and tagged surprise, curiosity, desire, ego, or fear. The winner is the highest score, and that line becomes the first spoken line of the video. The strategist is told not to copy a post or retell a third-party video.

The producer turns those spoken lines into a local Hypit template and renders pipeline/data/ready, followed by the run id, as an mp4. The run id starts with the local date and time. Generation-model imports are refused. The opening on-screen line is the hook the strategist kept.

The reviewer measures the file with ffprobe. It holds the file, and does not publish, if any of these are true: the render did not come from the local Hypit template, the file is missing or empty, the opening line is not the strategist’s hook, the duration is outside 20 to 30 seconds, or 3 videos are already scheduled for that calendar day. The daily cap in the config is 3.

The publisher runs only after a pass. It schedules the same video to TikTok, Instagram, and YouTube through Upload-Post. Facebook is not in this API. The slot is inside 08:00 to 22:00 in the timezone set in the config. The default timezone in the sample config is Asia/Kolkata. Hours from 22:00 through 08:00 are quiet. A fourth video on the same day is held. If the Upload-Post API key is missing, the video is held rather than posted. Upload-Post’s free tier allows 10 uploads a month, so three videos a day needs their paid plan. The operator creates a profile, the sample name is default, and connects TikTok, Instagram, and YouTube there. The key lives in pipeline/.env and is never committed.

The supervisor is the only writer of pipeline/data/supervisor.jsonl. A separate command, pipeline/assistant.py, answers questions about that log, such as what was held today. The assistant cannot render and cannot publish.

## Clipping a video you already own

Clipping is not part of the daily timer. The command is pipeline/openshorts_clip.py, plus a path or URL. It runs only after that source is listed under openshorts.allowlist in the config. An entry can be a channel id, an @handle, an exact URL, or a local directory. A YouTube link that is not on that list is refused. OpenShorts still requires a rights acknowledgement. This command sends that acknowledgement only after the allowlist check.

## How someone runs it

They install Docker, Python 3.11, Node.js 22.15 or newer, pnpm 10.33, Ollama, and FFmpeg. They clone this pipeline, clone OpenShorts beside it, and clone Hypit beside it at commit b00532e413d8. They pull qwen2.5:7b. They start OpenShorts with docker compose. The dashboard is localhost port 5175. They build Hypit’s public types and the chat-scene example. They create a Python 3.11 virtualenv in pipeline, install httpx and PyYAML, set the niche, and put the Upload-Post key in pipeline/.env. They run orchestrator.py once by hand. Only after that writes a file under pipeline/data/ready do they turn on a daily timer. The timer is a generic systemd service whose working directory is the pipeline folder. It is left off until the manual pass succeeds.

## What this is not

This is not a downloader for YouTube, Instagram, or TikTok.

It does not require a Gemini key, an ElevenLabs key, a fal.ai key, an AWS key, or a GPU for the daily short.

It does not call Hypit’s paid generation models on this path.

It is not OpenShorts Cloud, and it does not post to Facebook.

It does not describe a private server, a home network, a disk layout, or anyone else’s media apps. Those details are not part of this project.

## Credits

The pipeline code is MIT. OpenShorts core is MIT, except its cloud directory, which is commercial. Hypit is Apache-2.0 with extra conditions: using it on your own machine is allowed, and offering it as a hosted multi-tenant service is not. Videos made with Hypit belong to the person who made them. This project uses Hypit and OpenShorts. It did not write them.
