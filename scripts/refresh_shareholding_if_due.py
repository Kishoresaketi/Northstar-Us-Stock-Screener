#!/usr/bin/env python3
"""Monthly 13F refresh gate for the static-data build.

13F filings only change once a quarter, so the shareholding data is NOT
rebuilt on every full rebuild. This script decides whether a newer
completed quarter exists than the one in data/shareholding.json and,
only then, runs scripts/build_shareholding.py for it (full universe;
a fresh quarter downloads ~8,900 information tables, ~40 min). On every
other day it is a fast no-op: no downloads, nothing written.

It is called from scripts/build_static_data.py full mode (the daily
02:07 UTC workflow run), so a new quarter is picked up on the first full
rebuild after it becomes complete — a skipped workflow run just delays
it to the next full rebuild, it never misses a quarter. A failure here
must never break the daily rebuild: the caller wraps the call, and this
script exits non-zero only to signal the caller.

Runnable standalone:
    python3 scripts/refresh_shareholding_if_due.py                  # gate + build if due
    python3 scripts/refresh_shareholding_if_due.py --dry-run         # print the decision only
    python3 scripts/refresh_shareholding_if_due.py --as-of 2026-11-28  # pretend it is that date
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import date

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import lib.thirteenf as thirteenf

SHAREHOLDING_PATH = os.path.join(ROOT, "data", "shareholding.json")


def current_quarter(path=None):
    """Quarter end recorded in data/shareholding.json, or None if the
    file is missing or unreadable (which also means a refresh is due)."""
    try:
        with open(path or SHAREHOLDING_PATH, encoding="utf-8") as fh:
            payload = json.load(fh)
        return date.fromisoformat(payload["quarter"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def check_due(today=None, path=None):
    """(due, current, latest, label). due is True only when a newer
    completed quarter exists than the one already on disk."""
    today = today or date.today()
    latest, label = thirteenf.latest_completed_quarter(today)
    current = current_quarter(path)
    due = current is None or current < latest
    return due, current, latest, label


def run_build(quarter_end):
    """Run the 13F build + diagnostics refresh for quarter_end.
    Returns the build's exit code (0 = ok)."""
    build = subprocess.run(
        [sys.executable,
         os.path.join(ROOT, "scripts", "build_shareholding.py"),
         "--quarter", quarter_end.isoformat()],
        check=False,
    )
    if build.returncode != 0:
        return build.returncode
    # Best-effort diagnostics refresh; never fails the step.
    try:
        subprocess.run(
            [sys.executable,
             os.path.join(ROOT, "scripts", "validate_shareholding.py"),
             "--quarter", quarter_end.isoformat()],
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics are best-effort
        print(f"diagnostics refresh failed (non-fatal): {exc}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="print the decision without building anything")
    parser.add_argument("--as-of", default=None,
                        help="pretend today is YYYY-MM-DD (for testing)")
    args = parser.parse_args(argv)

    today = date.fromisoformat(args.as_of) if args.as_of else None
    due, current, latest, label = check_due(today)
    print(f"13F shareholding: on disk {current}, latest complete {latest} ({label})")
    if not due:
        print("13F shareholding is up to date; nothing to do.")
        return 0
    print(f"13F refresh due: building {label}.")
    if args.dry_run:
        print("dry run: build skipped.")
        return 0
    return run_build(latest)


if __name__ == "__main__":
    raise SystemExit(main())
