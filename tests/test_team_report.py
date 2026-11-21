from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import Client

from cora_mcp.server import mcp
from cora_mcp.team_report import _minimal_validate, build_report, load_standups, report_for


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "standups"
REPORT_DATE = "2026-11-19"

EXPECTED = """# Team report 2026-11-19

## Shipped

- **demo-ana**
  - [Stand-up schema draft](https://example.com/demo/pr/1)
  - Updated onboarding notes
- **demo-bo**
  - [Parser fix](https://example.com/demo/pr/2)

## Blocked

- demo-ana: Access request (since 2026-11-10, 9 days; unblocks: deploy preview)
- demo-ana: CI flaky (since 2026-11-10, 9 days; unblocks: merge of PR 1)
- demo-bo: API quota (since 2026-11-10, 9 days; unblocks: load test)
- demo-bo: Waiting on keys (since 2026-11-18, 1 day; unblocks: staging deploy)

## Needs the steward

- demo-bo: Approve test budget
- demo-dee: Decide report owner

## Open for anyone

- demo-ana: Review onboarding notes

## Missing

- demo-cy
- demo-eve
"""


class TeamReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        shutil.copytree(FIXTURES, self.repo / "CONTRIBUTIONS" / "standups")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_report_matches_expected_sections_and_order(self) -> None:
        report, _ = report_for(self.repo, REPORT_DATE)
        self.assertEqual(report, EXPECTED)

    def test_invalid_files_are_skipped_with_one_warning_each(self) -> None:
        records, warnings = load_standups(self.repo)
        self.assertEqual(len(records), 7)
        self.assertEqual(len(warnings), 2)
        self.assertIn("2026-11-16-demo-gus.json", warnings[0])
        self.assertIn("2026-11-17-demo-fay.json", warnings[1])
        self.assertNotIn("demo-fay", {record["member"] for record in records})

    def test_missing_uses_seven_day_window_and_ignores_invalid(self) -> None:
        report, _ = report_for(self.repo, REPORT_DATE)
        missing = report.split("## Missing\n\n", 1)[1]
        self.assertEqual(missing, "- demo-cy\n- demo-eve\n")

    def test_member_needs_are_not_reported(self) -> None:
        report, _ = report_for(self.repo, REPORT_DATE)
        self.assertNotIn("Pair on tests", report)

    def test_empty_sections_show_none(self) -> None:
        report = build_report([], REPORT_DATE)
        self.assertEqual(report.count("_None._"), 5)

    def test_output_is_byte_identical_across_runs(self) -> None:
        first, _ = report_for(self.repo, REPORT_DATE)
        second, _ = report_for(self.repo, REPORT_DATE)
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))

    def test_cli_writes_report_to_stdout_and_warnings_to_stderr(self) -> None:
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        result = subprocess.run(
            [sys.executable, "-m", "cora_mcp.team_report", "--date", REPORT_DATE, "--repo-root", str(self.repo)],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        self.assertEqual(result.stdout, EXPECTED)
        self.assertEqual(result.stderr.count("WARNING skipped"), 2)

    def test_fallback_validator_rejects_unknown_need_source(self) -> None:
        record = {
            "schema_version": "0.1",
            "date": REPORT_DATE,
            "member": "demo-ana",
            "shipped": [],
            "blocked": [],
            "need": [{"text": "x", "from": "boss"}],
        }
        self.assertEqual(_minimal_validate(record, "CONTRIBUTIONS/standups/2026-11-19-demo-ana.json"), ["need[0] is invalid"])


class TeamReportToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_tool_returns_report_and_rejects_bad_date(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("team_report", {"date": REPORT_DATE})
            self.assertFalse(result.is_error)
            self.assertTrue(result.content[0].text.startswith(f"# Team report {REPORT_DATE}\n"))

            bad = await client.call_tool("team_report", {"date": "yesterday"})
            self.assertTrue(bad.is_error)


if __name__ == "__main__":
    unittest.main()
