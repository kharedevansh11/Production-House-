#!/usr/bin/env python3
"""One daily pass: strategist, Hypit producer, reviewer, publisher, supervisor log."""

from __future__ import annotations

import argparse
import sys
import traceback
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from config_loader import niche_ready, load_config
from producer import render
from publisher import publish
from reviewer import review
from strategist import research
from supervisor import load_state, log, save_state


def run_once(config: dict | None = None) -> dict:
    config = config or load_config()
    if not niche_ready(config):
        raise SystemExit("Set niche in pipeline/config.yaml before running. It is still the placeholder.")
    run_id = datetime.now(ZoneInfo(config["timezone"])).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    state = load_state()
    log(run_id, "supervisor", "run_started", f"niche={config['niche']}")
    try:
        brief = research(config)
        log(
            run_id,
            "strategist",
            "brief_written",
            brief["hook"],
            search=brief["search"],
            angle=brief["chosen_angle"].get("topic"),
        )
        produced = render(brief, run_id, config)
        log(run_id, "producer", "rendered", produced["video"], build_id=produced["build_id"])
        verdict = review(produced, brief, state, config)
        log(
            run_id,
            "reviewer",
            "passed" if verdict["passed"] else "held",
            "; ".join(verdict["reasons"]) or "ok",
            scheduled_today=verdict["scheduled_today"],
        )
        if not verdict["passed"]:
            record = {"id": run_id, "status": "held", "hook": brief["hook"], "video": produced["video"], "reasons": verdict["reasons"]}
            state["runs"].append(record)
            save_state(state)
            log(run_id, "supervisor", "run_finished", "held")
            return record
        posted = publish(produced, brief, state, config)
        record = {
            "id": run_id,
            "status": posted["status"],
            "hook": brief["hook"],
            "video": produced["video"],
            "scheduled_date": posted.get("scheduled_date"),
            "reason": posted.get("reason"),
            "platforms": posted.get("platforms"),
        }
        state["runs"].append(record)
        save_state(state)
        log(run_id, "publisher", posted["status"], posted.get("reason") or posted.get("scheduled_date") or "")
        log(run_id, "supervisor", "run_finished", posted["status"])
        return record
    except Exception as exc:
        log(run_id, "supervisor", "run_failed", f"{exc.__class__.__name__}: {exc}")
        traceback.print_exc()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Hypit carousel pass")
    parser.parse_args()
    result = run_once()
    print(result["status"], result.get("hook", ""))


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc, file=sys.stderr)
        raise
