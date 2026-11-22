#!/usr/bin/env python3
"""Regression tests for the monthly 13F refresh gate
(scripts/refresh_shareholding_if_due.py).

The gate decides whether a newer completed 13F quarter exists than the
one in data/shareholding.json. It must be a no-op when up to date, must
trigger when a new quarter is complete, and must never mistake a missing
or corrupt shareholding file for "up to date".

Run:  python3 tests/test_refresh_shareholding_if_due.py
  or: python3 -m unittest discover -s tests -v

No network access: the build itself is never run here (run_build is
mocked out); only the gate decision is exercised.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scripts.refresh_shareholding_if_due as gate


def _write_shareholding(tmpdir, quarter):
    path = os.path.join(tmpdir, "shareholding.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"quarter": quarter, "entries": {}}, fh)
    return path


class GateTests(unittest.TestCase):
    def test_up_to_date_is_noop(self):
        # Q2 2026 is the latest complete quarter until Nov 28.
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_shareholding(tmpdir, "2026-06-30")
            due, current, latest, label = gate.check_due(
                date(2026, 11, 22), path)
            self.assertFalse(due)
            self.assertEqual(current, date(2026, 6, 30))
            self.assertEqual(latest, date(2026, 6, 30))
            self.assertEqual(label, "Q2 2026")

    def test_new_quarter_triggers(self):
        # From Nov 28 the Q3 deadline + grace period has passed.
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_shareholding(tmpdir, "2026-06-30")
            due, current, latest, label = gate.check_due(
                date(2026, 11, 28), path)
            self.assertTrue(due)
            self.assertEqual(latest, date(2026, 9, 30))
            self.assertEqual(label, "Q3 2026")

    def test_missing_file_triggers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "shareholding.json")
            due, current, latest, _label = gate.check_due(
                date(2026, 11, 22), path)
            self.assertTrue(due)
            self.assertIsNone(current)

    def test_corrupt_file_triggers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "shareholding.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            due, current, _latest, _label = gate.check_due(
                date(2026, 11, 22), path)
            self.assertTrue(due)
            self.assertIsNone(current)

    def test_main_up_to_date_never_builds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_shareholding(tmpdir, "2026-06-30")
            with mock.patch.object(gate, "SHAREHOLDING_PATH", path):
                with mock.patch.object(gate, "run_build") as build:
                    self.assertEqual(gate.main(["--as-of", "2026-11-22"]), 0)
                    build.assert_not_called()

    def test_main_dry_run_never_builds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_shareholding(tmpdir, "2026-06-30")
            with mock.patch.object(gate, "SHAREHOLDING_PATH", path):
                with mock.patch.object(gate, "run_build") as build:
                    self.assertEqual(
                        gate.main(["--as-of", "2026-11-28", "--dry-run"]), 0)
                    build.assert_not_called()

    def test_main_due_builds_latest_quarter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_shareholding(tmpdir, "2026-06-30")
            with mock.patch.object(gate, "SHAREHOLDING_PATH", path):
                with mock.patch.object(gate, "run_build",
                                       return_value=0) as build:
                    self.assertEqual(gate.main(["--as-of", "2026-11-28"]), 0)
                    build.assert_called_once_with(date(2026, 9, 30))


if __name__ == "__main__":
    unittest.main()
