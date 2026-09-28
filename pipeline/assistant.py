#!/usr/bin/env python3
"""Read-only assistant. It can see the supervisor log and state. It cannot render or publish."""

from __future__ import annotations

import argparse
import sys

from config_loader import load_config
from llm import complete
from supervisor import load_state, read_log


def summary() -> str:
    rows = read_log()
    state = load_state()
    if not rows and not state.get("runs"):
        return "No runs yet. The supervisor log is empty."
    lines = [f"{len(rows)} log lines, {len(state.get('runs') or [])} runs."]
    for row in rows[-12:]:
        lines.append(f"{row.get('ts')} {row.get('agent')} {row.get('event')}: {row.get('summary')}")
    held = [run for run in state.get("runs") or [] if run.get("status") == "held"]
    scheduled = [run for run in state.get("runs") or [] if run.get("status") == "scheduled"]
    if scheduled:
        lines.append("Scheduled:")
        for run in scheduled[-5:]:
            lines.append(f"  {run.get('scheduled_date')} {run.get('hook')}")
    if held:
        lines.append("Held:")
        for run in held[-5:]:
            lines.append(f"  {run.get('hook')} — {run.get('reason') or run.get('reasons')}")
    return "\n".join(lines)


def answer(question: str) -> str:
    base = summary()
    if not question.strip():
        return base
    try:
        config = load_config()
        ollama = config["ollama"]
        text = complete(
            ollama["base_url"],
            ollama["model"],
            "You are a read-only assistant for a local video pipeline. "
            "Answer only from the log below. Do not invent posts. "
            "You cannot render or publish.",
            f"Log:\n{base}\n\nQuestion: {question}",
            timeout=90,
        )
        return text.strip() or base
    except Exception as exc:
        return base + f"\n\n(Ollama unavailable: {exc.__class__.__name__}. Showing the log as-is.)"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask about the supervisor log")
    parser.add_argument("question", nargs="*", help="optional question")
    args = parser.parse_args()
    print(answer(" ".join(args.question)))


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
