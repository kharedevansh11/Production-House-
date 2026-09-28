"""Local Ollama chat client. OpenAI-compatible /v1/chat/completions."""

from __future__ import annotations

import json

import httpx


def parse_json_object(text: str) -> dict:
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[1]
        body = body.rsplit("```", 1)[0]
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"model did not return JSON: {text[:240]}")
    return json.loads(body[start : end + 1])


def complete(base_url: str, model: str, system: str, user: str, timeout: float = 180) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    response = httpx.post(
        url,
        json={
            "model": model,
            "temperature": 0.4,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]
