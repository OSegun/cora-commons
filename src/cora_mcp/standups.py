"""Deterministic validation for public Cora Commons stand-up records."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


MEMBER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
DATE_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[-. ]?)?(?:\(?\d{2,4}\)?[-. ]?){2,3}\d{3,4}(?!\w)")
MAX_ITEMS = 20
NEED_SOURCES = {"steward", "member", "anyone"}


def _required_string(record: dict[str, Any], field: str, errors: list[str], prefix: str = "") -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{prefix}{field} must be a non-empty string")
        return ""
    return value.strip()


def _date_value(value: object, field: str, errors: list[str]) -> date | None:
    if not isinstance(value, str) or not DATE_TEXT.fullmatch(value):
        errors.append(f"{field} must be a YYYY-MM-DD date")
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        errors.append(f"{field} must be a real calendar date")
        return None
    if parsed > date.today():
        errors.append(f"{field} must not be in the future")
    return parsed


def _public_string(value: str, field: str, errors: list[str]) -> None:
    if EMAIL.search(value) or PHONE.search(value):
        errors.append(f"{field} must not contain an email address or phone number")


def _check_public_strings(value: object, field: str, errors: list[str]) -> None:
    """Reject email and phone-like content in every public JSON string value."""
    pending: list[tuple[object, str]] = [(value, field)]
    while pending:
        current, current_field = pending.pop()
        if isinstance(current, str):
            _public_string(current, current_field, errors)
        elif isinstance(current, list):
            for index in range(len(current) - 1, -1, -1):
                pending.append((current[index], f"{current_field}[{index}]"))
        elif isinstance(current, dict):
            for key in reversed(current):
                name = str(key)
                child = f"{current_field}.{name}" if current_field else name
                pending.append((current[key], child))


def _validate_list(value: object, field: str, errors: list[str]) -> list[object] | None:
    if not isinstance(value, list):
        errors.append(f"{field} must be a list")
        return None
    if len(value) > MAX_ITEMS:
        errors.append(f"{field} must contain at most {MAX_ITEMS} items")
    return value


def validate_standup(data: object, filename: str | Path | None = None) -> list[str]:
    """Return all validation errors; an empty list means the record is valid."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["stand-up record must be a JSON object"]

    if data.get("schema_version") != "0.1":
        errors.append("schema_version must be 0.1")

    record_date = _date_value(data.get("date"), "date", errors)
    member = _required_string(data, "member", errors)
    if member:
        if not MEMBER_ID.fullmatch(member):
            errors.append("member must be a GitHub handle or agent id")

    shipped = _validate_list(data.get("shipped"), "shipped", errors)
    if shipped is not None:
        for index, item in enumerate(shipped):
            prefix = f"shipped[{index}]."
            if not isinstance(item, dict):
                errors.append(f"shipped[{index}] must be an object")
                continue
            _required_string(item, "text", errors, prefix)
            if "link" in item:
                _required_string(item, "link", errors, prefix)

    blocked = _validate_list(data.get("blocked"), "blocked", errors)
    if blocked is not None:
        for index, item in enumerate(blocked):
            prefix = f"blocked[{index}]."
            if not isinstance(item, dict):
                errors.append(f"blocked[{index}] must be an object")
                continue
            _required_string(item, "text", errors, prefix)
            _date_value(item.get("since"), f"{prefix}since", errors)
            _required_string(item, "unblocks", errors, prefix)

    needs = _validate_list(data.get("need"), "need", errors)
    if needs is not None:
        for index, item in enumerate(needs):
            prefix = f"need[{index}]."
            if not isinstance(item, dict):
                errors.append(f"need[{index}] must be an object")
                continue
            _required_string(item, "text", errors, prefix)
            source = item.get("from")
            if not isinstance(source, str) or source not in NEED_SOURCES:
                errors.append(f"{prefix}from must be steward, member or anyone")

    if filename is not None and record_date is not None and member:
        expected = f"CONTRIBUTIONS/standups/{record_date.isoformat()}-{member}.json"
        actual = Path(filename).as_posix()
        if actual != expected:
            errors.append(f"filename must be {expected}")

    _check_public_strings(data, "", errors)
    return errors


def load_standup(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_path(path: Path, repo_root: Path) -> list[str]:
    try:
        data = load_standup(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read valid JSON: {exc}"]
    try:
        filename = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return [f"path must be inside repository root: {path}"]
    if filename.parent == Path("CONTRIBUTIONS/examples"):
        return validate_standup(data)
    return validate_standup(data, filename)


def standup_paths(repo_root: Path) -> list[Path]:
    canonical = (repo_root / "CONTRIBUTIONS" / "standups").glob("*.json")
    examples = (repo_root / "CONTRIBUTIONS" / "examples").glob("STANDUP-*.json")
    return sorted((*canonical, *examples), key=lambda path: path.as_posix())


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Cora Commons stand-up records")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_all = subparsers.add_parser("validate-all")
    validate_all.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    paths = standup_paths(repo_root)
    failed = False
    for path in paths:
        errors = validate_path(path, repo_root)
        if errors:
            failed = True
            print(f"INVALID {path}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"VALID {path}")
    if not paths:
        print("VALID no stand-up records or examples yet")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
