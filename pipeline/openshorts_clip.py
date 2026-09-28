"""Clip a long video you own. Refuses anything that is not on the allowlist.

OpenShorts still requires acknowledged=true. This module only sends that flag
after the allowlist check. It does not search YouTube.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().split(":")[0]


def source_allowed(source: str, allowlist: dict) -> bool:
    candidate = Path(source).expanduser()
    if candidate.exists():
        resolved = candidate.resolve()
        for directory in allowlist.get("local_dirs") or []:
            root = Path(directory).expanduser().resolve()
            if resolved == root or root in resolved.parents:
                return True
        return False
    parsed = urlparse(source)
    if parsed.scheme not in ("http", "https"):
        return False
    host = _host(source)
    if host not in YOUTUBE_HOSTS and not host.endswith(".youtube.com"):
        return False
    if source in (allowlist.get("urls") or []):
        return True
    for channel_id in allowlist.get("channel_ids") or []:
        token = str(channel_id).strip()
        if token and token in source:
            return True
    for handle in allowlist.get("handles") or []:
        token = str(handle).strip()
        if not token:
            continue
        if not token.startswith("@"):
            token = "@" + token
        if token.lower() in source.lower():
            return True
    return False


def clip_owned(source: str, config: dict) -> dict:
    allowlist = config["openshorts"]["allowlist"]
    if not source_allowed(source, allowlist):
        raise PermissionError(
            "Refusing to clip: the source is not on openshorts.allowlist. "
            "Add your channel id, a handle, an exact URL, or a local directory you own."
        )
    api = config["openshorts"]["api_url"].rstrip("/")
    if Path(source).expanduser().exists():
        path = Path(source).expanduser()
        with path.open("rb") as handle:
            response = httpx.post(
                f"{api}/api/process",
                data={"acknowledged": "true", "output_format": "vertical", "target_clips": "3"},
                files={"file": (path.name, handle, "video/mp4")},
                timeout=120,
            )
    else:
        response = httpx.post(
            f"{api}/api/process",
            json={
                "url": source,
                "acknowledged": True,
                "output_format": "vertical",
                "target_clips": 3,
            },
            timeout=120,
        )
    response.raise_for_status()
    return response.json()


def main() -> None:
    import argparse
    import json

    from config_loader import load_config

    parser = argparse.ArgumentParser(description="Clip one long video you own")
    parser.add_argument("source", help="allowlisted YouTube URL or local file")
    args = parser.parse_args()
    print(json.dumps(clip_owned(args.source, load_config()), indent=2))


if __name__ == "__main__":
    main()
