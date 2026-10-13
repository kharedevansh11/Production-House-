#!/usr/bin/env bash
# The only command you need for the studio on smaug. Run it from any laptop on the home network:
#
#   bash studio.sh                              # first time: installs and starts everything (re-run to update)
#   bash studio.sh quiz --topic "human body"    # make a video (any studio.py arguments)
#   bash studio.sh ghar --draft                 # write a Hindi household scene to check first
#   bash studio.sh status                       # what is running, and the latest log lines
#
# Run from another machine, it logs into smaug over SSH and runs itself there.
set -euo pipefail

SMAUG=${SMAUG:-keeper@192.168.1.30}
REPO_URL=${REPO_URL:-https://github.com/kharedevansh11/Production-House-.git}
BRANCH=${BRANCH:-studio-pipeline}
BASE=/mnt/ssd-ext/amrit
CODE=$BASE/projects/Production-House-
DATA=$BASE/data/studio
STACK=$CODE/pipeline/studio

if [ ! -d "$BASE" ]; then
  exec ssh -t "$SMAUG" "SMAUG=$SMAUG REPO_URL=$REPO_URL BRANCH=$BRANCH bash -s -- $(printf '%q ' "$@")" < "$0"
fi

setup() {
  mkdir -p "$BASE/projects" "$DATA"/{work/in,public,hf-cache,acestep-checkpoints}
  if [ -d "$CODE/.git" ]; then
    git -C "$CODE" pull --ff-only
  else
    git clone -b "$BRANCH" "$REPO_URL" "$CODE"
  fi
  docker network inspect amrit_sandbox >/dev/null 2>&1 || docker network create amrit_sandbox

  if ! grep -q '^HF_TOKEN=hf_' "$STACK/.env" 2>/dev/null; then
    echo
    echo "The Hindi voice model needs a free Hugging Face token:"
    echo "  1. accept its terms at https://huggingface.co/ai4bharat/indic-parler-tts"
    echo "  2. create a 'read' token at https://huggingface.co/settings/tokens"
    read -rsp "Paste the token (hidden, Enter to skip): " token </dev/tty
    echo
    if [ -n "$token" ]; then
      printf 'HF_TOKEN=%s\n' "$token" > "$STACK/.env"
      chmod 600 "$STACK/.env"
    fi
  fi

  docker exec amrit-ollama ollama list | grep -q 'gemma3:12b' || docker exec amrit-ollama ollama pull gemma3:12b
  cd "$STACK"
  echo "Building and starting the services. The first time takes 20-40 minutes."
  docker compose up -d --build
  docker compose --profile job build
  echo
  docker ps --filter name=amrit --format '{{.Names}}\t{{.Status}}'
  echo
  echo "Ready. Make a video with:  bash studio.sh quiz --topic \"human body\""
  echo "Watch and download at:     http://192.168.1.30:9103"
}

make_video() {
  cd "$STACK"
  name="amrit-studio-job-$(date +%Y%m%d-%H%M%S)"
  # detached, so a dropped SSH connection does not kill a long render
  docker compose run -d --rm --name "$name" studio python studio.py "$@" >/dev/null
  echo "Started $name. Following its log (Ctrl+C stops following; the render keeps going)."
  docker logs -f "$name" || true
  echo "Videos: http://192.168.1.30:9103"
}

status() {
  docker ps --filter name=amrit --format '{{.Names}}\t{{.Status}}'
  tail -n 15 "$CODE/pipeline/data/supervisor.jsonl" 2>/dev/null || echo "No runs yet."
}

case "${1:-setup}" in
  setup) setup ;;
  status) status ;;
  *) make_video "$@" ;;
esac
