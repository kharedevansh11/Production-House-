"""Load pipeline/config.yaml and pipeline/.env."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
ENV_PATH = ROOT / ".env"
DATA = ROOT / "data"
TEMPLATE = ROOT / "template"
REPO = ROOT.parent
HYPIT_REPO = REPO / "hypit"
NICHE_PLACEHOLDER = "REPLACE_WITH_YOUR_NICHE"


def load_env(path: Path = ENV_PATH) -> None:
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path: Path = CONFIG_PATH) -> dict:
    load_env()
    with path.open() as handle:
        config = yaml.safe_load(handle)
    profile = os.environ.get("UPLOAD_POST_PROFILE")
    if profile:
        config.setdefault("upload_post", {})["profile"] = profile
    config["_root"] = str(ROOT)
    return config


def niche_ready(config: dict) -> bool:
    niche = str(config.get("niche", "")).strip()
    return bool(niche) and niche != NICHE_PLACEHOLDER
