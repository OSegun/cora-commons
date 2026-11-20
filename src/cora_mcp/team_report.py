"""Deterministic team report built from public Cora Commons stand-up records."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date as Date, timedelta
from pathlib import Path
from typing import Any, Callable


ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NEED_SOURCES = {"steward", "member", "anyone"}


def _is_date(value: object) -> bool:
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value):
        return False
    try:
        Date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _minimal_validate(data: object, filename: str | None = None) -> list[str]:
    """Fallback used until cora_mcp.standups (issue #35) is available."""
    if not isinstance(data, dict):
        return ["stand-up must be a JSON object"]
    errors: list[str] = []
    if data.get("schema_version") != "0.1":
        errors.append("schema_version must be 0.1")
    if not _is_date(data.get("date")):
        errors.append("date must be YYYY-MM-DD")
    if not _text(data.get("member")):
        errors.append("member must be a non-empty string")
    expected = f"CONTRIBUTIONS/standups/{data.get('date')}-{data.get('member')}.json"
    if filename and not errors and Path(filename).as_posix() != expected:
        errors.append(f"filename must be {expected}")

    item_rules = {
        "shipped": lambda item: _text(item.get("text")) and (item.get("link") is None or _text(item.get("link"))),
        "blocked": lambda item: _text(item.get("text")) and _is_date(item.get("since")) and _text(item.get("unblocks")),
        "need": lambda item: _text(item.get("text")) and item.get("from") in NEED_SOURCES,
    }
    for field, rule in item_rules.items():
        items = data.get(field)
        if not isinstance(items, list):
            errors.append(f"{field} must be a list")
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict) or not rule(item):
                errors.append(f"{field}[{index}] is invalid")
    return errors


try:
    from .standups import validate_standup as _validate
except ImportError:
    _validate = _minimal_validate

validate: Callable[[object, str | None], list[str]] = _validate


def standup_paths(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "CONTRIBUTIONS" / "standups").glob("*.json"))


def load_standups(repo_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Return valid stand-up records and one warning per skipped file."""
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    for path in standup_paths(repo_root):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"WARNING skipped {path.name}: cannot read valid JSON: {exc}")
            continue
        errors = validate(data, f"CONTRIBUTIONS/standups/{path.name}")
        if errors:
            warnings.append(f"WARNING skipped {path.name}: {'; '.join(errors)}")
            continue
        records.append(data)
    return records, warnings


MISSING_WINDOW_DAYS = 7
NONE = "_None._"


def _section(title: str, lines: list[str]) -> list[str]:
    return [f"## {title}", "", *(lines or [NONE]), ""]


def _needs(today: list[dict[str, Any]], source: str) -> list[str]:
    return [
        f"- {record['member']}: {item['text']}"
        for record in today
        for item in record["need"]
        if item["from"] == source
    ]


def build_report(records: list[dict[str, Any]], report_date: str) -> str:
    """Render one day's valid stand-up records as a deterministic Markdown report."""
    day = Date.fromisoformat(report_date)
    today = sorted((r for r in records if r["date"] == report_date), key=lambda r: r["member"])

    shipped: list[str] = []
    for record in today:
        if not record["shipped"]:
            continue
        shipped.append(f"- **{record['member']}**")
        for item in record["shipped"]:
            text = f"[{item['text']}]({item['link']})" if item.get("link") else item["text"]
            shipped.append(f"  - {text}")

    blockers = sorted(
        ((item["since"], record["member"], item["text"], item["unblocks"]) for record in today for item in record["blocked"]),
    )
    blocked = []
    for since, member, text, unblocks in blockers:
        days = (day - Date.fromisoformat(since)).days
        blocked.append(f"- {member}: {text} (since {since}, {days} {'day' if days == 1 else 'days'}; unblocks: {unblocks})")

    window_start = day - timedelta(days=MISSING_WINDOW_DAYS)
    recent = {r["member"] for r in records if window_start <= Date.fromisoformat(r["date"]) < day}
    reported_today = {r["member"] for r in today}
    missing = [f"- {member}" for member in sorted(recent - reported_today)]

    lines = [f"# Team report {report_date}", ""]
    lines += _section("Shipped", shipped)
    lines += _section("Blocked", blocked)
    lines += _section("Needs the steward", _needs(today, "steward"))
    lines += _section("Open for anyone", _needs(today, "anyone"))
    lines += _section("Missing", missing)
    return "\n".join(lines).rstrip("\n") + "\n"


def report_for(repo_root: Path, report_date: str) -> tuple[str, list[str]]:
    if not _is_date(report_date):
        raise ValueError("date must be YYYY-MM-DD")
    records, warnings = load_standups(repo_root)
    return build_report(records, report_date), warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Roll one day's Cora Commons stand-ups into a team report")
    parser.add_argument("--date", required=True, help="report date, YYYY-MM-DD")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if not _is_date(args.date):
        parser.error("--date must be YYYY-MM-DD")

    report, warnings = report_for(args.repo_root.resolve(), args.date)
    for warning in warnings:
        print(warning, file=sys.stderr)
    sys.stdout.write(report)


if __name__ == "__main__":
    main()
