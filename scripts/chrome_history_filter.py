"""Export Chrome history from local profiles and filter known websites.

The script only reads local Chrome SQLite databases. It copies each History DB
to a temporary file first so it can run while Chrome is open.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


UTC = timezone.utc
CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class HistoryEntry:
    profile: str
    visit_time_utc: str
    site: str
    url: str
    title: str
    transition: int | None


@dataclass(frozen=True)
class ExcludeRule:
    raw: str
    kind: str
    value: str
    regex: re.Pattern[str] | None = None


def chrome_time_to_iso(value: int) -> str:
    if not value:
        return ""
    timestamp = CHROME_EPOCH.timestamp() + (value / 1_000_000)
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def default_chrome_user_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if sys.platform.startswith("win") and local_app_data:
        return Path(local_app_data) / "Google" / "Chrome" / "User Data"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome"

    return Path.home() / ".config" / "google-chrome"


def iter_history_dbs(user_data_dir: Path) -> Iterable[tuple[str, Path]]:
    if not user_data_dir.exists():
        return

    for profile_dir in sorted(user_data_dir.iterdir()):
        if not profile_dir.is_dir():
            continue

        history_db = profile_dir / "History"
        if history_db.exists():
            yield profile_dir.name, history_db


def load_exclude_rules(path: Path | None) -> list[ExcludeRule]:
    if path is None:
        return []

    rules: list[ExcludeRule] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue

        if raw.startswith("re:"):
            pattern = raw[3:]
            try:
                rules.append(ExcludeRule(raw=raw, kind="regex", value=pattern, regex=re.compile(pattern, re.I)))
            except re.error as exc:
                raise ValueError(f"Invalid regex at {path}:{line_number}: {exc}") from exc
            continue

        parsed = urlparse(raw if "://" in raw else f"//{raw}")
        host = (parsed.hostname or "").lower().lstrip(".")

        if "://" in raw:
            rules.append(ExcludeRule(raw=raw, kind="url_prefix", value=raw.lower().rstrip("/")))
        elif host and "/" not in raw and " " not in raw:
            rules.append(ExcludeRule(raw=raw, kind="domain", value=host.removeprefix("*.")))
        else:
            rules.append(ExcludeRule(raw=raw, kind="substring", value=raw.lower()))

    return rules


def is_excluded(url: str, rules: list[ExcludeRule]) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    lowered_url = url.lower()

    for rule in rules:
        if rule.kind == "regex" and rule.regex and rule.regex.search(url):
            return True

        if rule.kind == "url_prefix" and lowered_url.rstrip("/").startswith(rule.value):
            return True

        if rule.kind == "domain" and (host == rule.value or host.endswith(f".{rule.value}")):
            return True

        if rule.kind == "substring" and rule.value in lowered_url:
            return True

    return False


def site_from_url(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def copy_sqlite_snapshot(source_db: Path, temp_dir: Path) -> Path:
    """Copy SQLite DB plus WAL sidecars so live Chrome history is complete."""
    target_db = temp_dir / "History"
    shutil.copy2(source_db, target_db)

    for suffix in ("-wal", "-shm"):
        sidecar = source_db.with_name(f"{source_db.name}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, temp_dir / sidecar.name)

    return target_db


def read_profile_history(profile: str, history_db: Path, since_chrome_time: int | None) -> list[HistoryEntry]:
    entries: list[HistoryEntry] = []

    with tempfile.TemporaryDirectory(prefix=f"chrome-history-{profile}-") as temp_name:
        snapshot_db = copy_sqlite_snapshot(history_db, Path(temp_name))
        conn = sqlite3.connect(f"file:{snapshot_db}?mode=ro", uri=True)
        try:
            query = """
                SELECT urls.url, urls.title, visits.visit_time, visits.transition
                FROM visits
                JOIN urls ON visits.url = urls.id
            """
            params: tuple[int, ...] = ()
            if since_chrome_time is not None:
                query += " WHERE visits.visit_time >= ?"
                params = (since_chrome_time,)

            query += " ORDER BY visits.visit_time DESC"

            for url, title, visit_time, transition in conn.execute(query, params):
                normalized_url = url or ""
                entries.append(
                    HistoryEntry(
                        profile=profile,
                        visit_time_utc=chrome_time_to_iso(int(visit_time or 0)),
                        site=site_from_url(normalized_url),
                        url=normalized_url,
                        title=title or "",
                        transition=transition,
                    )
                )
        finally:
            conn.close()

    return entries


def only_sites_below_visit_count(entries: list[HistoryEntry], max_visits_exclusive: int | None) -> list[HistoryEntry]:
    if max_visits_exclusive is None:
        return entries

    counts: dict[str, int] = {}
    for entry in entries:
        if not entry.site:
            continue
        counts[entry.site] = counts.get(entry.site, 0) + 1

    return [
        entry
        for entry in entries
        if entry.site and counts.get(entry.site, 0) < max_visits_exclusive
    ]


def parse_since(value: str | None) -> int | None:
    if not value:
        return None

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    seconds = parsed.astimezone(UTC).timestamp() - CHROME_EPOCH.timestamp()
    return int(seconds * 1_000_000)


def write_csv(entries: list[HistoryEntry], output: Path | None) -> None:
    fieldnames = ["profile", "visit_time_utc", "site", "url", "title", "transition"]
    stream = output.open("w", encoding="utf-8", newline="") if output else sys.stdout
    try:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry.__dict__)
    finally:
        if output:
            stream.close()


def write_jsonl(entries: list[HistoryEntry], output: Path | None) -> None:
    stream = output.open("w", encoding="utf-8") if output else sys.stdout
    try:
        for entry in entries:
            stream.write(json.dumps(entry.__dict__, ensure_ascii=False) + "\n")
    finally:
        if output:
            stream.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export Chrome browsing history from local profiles and filter known websites.",
    )
    parser.add_argument(
        "--chrome-user-data",
        type=Path,
        default=default_chrome_user_data_dir(),
        help="Chrome User Data directory. Defaults to the current OS Chrome profile path.",
    )
    parser.add_argument(
        "--exclude",
        type=Path,
        help="Text file with websites to remove. Supports domains, URL prefixes, substrings, and re:<regex>.",
    )
    parser.add_argument(
        "--since",
        help="Only include visits since an ISO date/time, for example 2026-04-01 or 2026-04-01T10:00:00+07:00.",
    )
    parser.add_argument("--limit", type=int, help="Maximum number of rows after filtering.")
    parser.add_argument(
        "--max-site-visits-exclusive",
        type=int,
        help="Only keep entries whose hostname appears fewer than this many times after exclude filtering.",
    )
    parser.add_argument("--output", type=Path, help="Output file. Defaults to stdout.")
    parser.add_argument("--format", choices=("csv", "jsonl"), default="csv", help="Output format.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        rules = load_exclude_rules(args.exclude)
        since_chrome_time = parse_since(args.since)
    except ValueError as exc:
        parser.error(str(exc))

    entries: list[HistoryEntry] = []
    for profile, history_db in iter_history_dbs(args.chrome_user_data):
        entries.extend(read_profile_history(profile, history_db, since_chrome_time))

    filtered = [entry for entry in entries if not is_excluded(entry.url, rules)]
    filtered = only_sites_below_visit_count(filtered, args.max_site_visits_exclusive)
    filtered.sort(key=lambda entry: entry.visit_time_utc, reverse=True)

    if args.limit is not None:
        filtered = filtered[: args.limit]

    if args.format == "jsonl":
        write_jsonl(filtered, args.output)
    else:
        write_csv(filtered, args.output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
