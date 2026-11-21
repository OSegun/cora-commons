from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from cora_mcp import standups


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = [
    json.loads((ROOT / "CONTRIBUTIONS" / "examples" / name).read_text(encoding="utf-8"))
    for name in ("STANDUP-EXAMPLE-0001.json", "STANDUP-EXAMPLE-0002.json")
]


class StandupValidationTests(unittest.TestCase):
    def test_examples_are_valid(self) -> None:
        for record in EXAMPLES:
            self.assertEqual(validate_errors(record), [])

    def test_rejects_invalid_types_and_empty_text(self) -> None:
        record = copy.deepcopy(EXAMPLES[0])
        record["shipped"] = "not a list"
        record["need"] = [{"text": "", "from": "member"}]
        errors = validate_errors(record)
        self.assertIn("shipped must be a list", errors)
        self.assertIn("need[0].text must be a non-empty string", errors)

    def test_rejects_invalid_and_future_dates(self) -> None:
        record = copy.deepcopy(EXAMPLES[0])
        record["date"] = "2026-02-30"
        record["blocked"] = [{"text": "Waiting", "since": (date.today() + timedelta(days=1)).isoformat(), "unblocks": "Review"}]
        errors = validate_errors(record)
        self.assertIn("date must be a real calendar date", errors)
        self.assertIn("blocked[0].since must not be in the future", errors)

    def test_rejects_invalid_member_and_public_pii(self) -> None:
        record = copy.deepcopy(EXAMPLES[0])
        record["member"] = "person@example.com"
        record["shipped"][0]["text"] = "Call +1 202-555-0199 after review"
        record["metadata"] = {"contact": "another.person@example.com"}
        errors = validate_errors(record)
        self.assertIn("member must be a GitHub handle or agent id", errors)
        self.assertIn("member must not contain an email address or phone number", errors)
        self.assertIn("shipped[0].text must not contain an email address or phone number", errors)
        self.assertIn("metadata.contact must not contain an email address or phone number", errors)
        self.assertEqual(errors.count("member must not contain an email address or phone number"), 1)

    def test_deeply_nested_public_data_does_not_crash(self) -> None:
        record = copy.deepcopy(EXAMPLES[0])
        nested: dict[str, object] = record
        for _ in range(1_200):
            child: dict[str, object] = {}
            nested["metadata"] = child
            nested = child
        self.assertEqual(validate_errors(record), [])

    def test_rejects_more_than_twenty_items_per_list(self) -> None:
        record = copy.deepcopy(EXAMPLES[0])
        record["shipped"] = [{"text": "Completed work"} for _ in range(21)]
        record["blocked"] = [{"text": "Waiting", "since": "2026-11-20", "unblocks": "Review"} for _ in range(21)]
        record["need"] = [{"text": "Reviewer", "from": "anyone"} for _ in range(21)]
        errors = validate_errors(record)
        self.assertIn("shipped must contain at most 20 items", errors)
        self.assertIn("blocked must contain at most 20 items", errors)
        self.assertIn("need must contain at most 20 items", errors)

    def test_rejects_invalid_nested_fields_and_need_source(self) -> None:
        record = copy.deepcopy(EXAMPLES[0])
        record["blocked"] = [{"text": "Waiting", "since": "not-a-date", "unblocks": ""}]
        record["need"] = [{"text": "Reviewer", "from": "outside"}]
        errors = validate_errors(record)
        self.assertIn("blocked[0].since must be a YYYY-MM-DD date", errors)
        self.assertIn("blocked[0].unblocks must be a non-empty string", errors)
        self.assertIn("need[0].from must be steward, member or anyone", errors)

    def test_malformed_need_source_does_not_crash_validation(self) -> None:
        for source in (["member"], {"source": "member"}):
            with self.subTest(source=source):
                record = copy.deepcopy(EXAMPLES[0])
                record["need"] = [{"text": "Reviewer", "from": source}]
                self.assertIn("need[0].from must be steward, member or anyone", validate_errors(record))

    def test_filename_must_match_canonical_record_path(self) -> None:
        record = EXAMPLES[0]
        expected = "CONTRIBUTIONS/standups/2026-11-20-example-human.json"
        self.assertEqual(validate_errors(record, expected), [])
        self.assertIn("filename must be " + expected, validate_errors(record, "wrong.json"))

    def test_validate_all_includes_examples(self) -> None:
        exit_code, output = run_cli(ROOT)
        self.assertEqual(exit_code, 0)
        self.assertIn("VALID " + str(ROOT / "CONTRIBUTIONS" / "examples" / "STANDUP-EXAMPLE-0001.json"), output)
        self.assertIn("VALID " + str(ROOT / "CONTRIBUTIONS" / "examples" / "STANDUP-EXAMPLE-0002.json"), output)

    def test_validate_all_reports_valid_and_invalid_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            records = root / "CONTRIBUTIONS" / "standups"
            records.mkdir(parents=True)
            valid_path = records / "2026-11-20-example-human.json"
            valid_path.write_text(json.dumps(EXAMPLES[0]), encoding="utf-8")
            exit_code, output = run_cli(root)
            self.assertEqual(exit_code, 0)
            self.assertIn(f"VALID {valid_path.resolve()}", output)

            (records / "2026-11-20-bad.json").write_text("{not json", encoding="utf-8")
            exit_code, output = run_cli(root)
            self.assertEqual(exit_code, 1)
            self.assertIn("INVALID", output)
            self.assertIn("cannot read valid JSON", output)


def validate_errors(record: object, filename: str | None = None) -> list[str]:
    return standups.validate_standup(record, filename)


def run_cli(repo_root: Path) -> tuple[int, str]:
    output = io.StringIO()
    with patch.object(sys, "argv", ["standups", "validate-all", "--repo-root", str(repo_root)]), redirect_stdout(output):
        with unittest.TestCase().assertRaises(SystemExit) as exited:
            standups.main()
    return int(exited.exception.code), output.getvalue()


if __name__ == "__main__":
    unittest.main()
