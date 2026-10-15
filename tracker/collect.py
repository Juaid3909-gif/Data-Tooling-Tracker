"""Collect one daily snapshot of repository metrics from the GitHub REST API.

The store is a single append-friendly CSV (`data/snapshots.csv`) with one row per
(snapshot_date, repo). Re-running on the same day replaces that day's rows (idempotent),
which makes the scheduled job safe to retry.
"""
from __future__ import annotations

import csv
import datetime as dt
import logging
import os
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import API_ROOT, DEFAULT_DATA_PATH, REPOS

log = logging.getLogger(__name__)

FIELDS = [
    "snapshot_date", "repo", "stars", "forks", "open_issues", "watchers",
    "size_kb", "pushed_at", "latest_release_tag", "latest_release_at",
]


class RateLimited(RuntimeError):
    pass


def make_session(token: str | None = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/vnd.github+json", "User-Agent": "data-tooling-tracker"})
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(500, 502, 503, 504), allowed_methods=("GET",))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _get(session, url: str, allow_404: bool = False):
    r = session.get(url, timeout=30)
    if r.status_code == 404 and allow_404:
        return None
    if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
        raise RateLimited(f"GitHub rate limit hit (resets at epoch {r.headers.get('X-RateLimit-Reset')}). "
                          "Set GITHUB_TOKEN to raise the limit from 60 to 5000 requests/hour.")
    r.raise_for_status()
    return r.json()


def fetch_snapshot(session, full_name: str, today: dt.date) -> dict:
    repo = _get(session, f"{API_ROOT}/repos/{full_name}")
    release = _get(session, f"{API_ROOT}/repos/{full_name}/releases/latest", allow_404=True)
    return {
        "snapshot_date": today.isoformat(),
        "repo": full_name,
        "stars": repo["stargazers_count"],
        "forks": repo["forks_count"],
        "open_issues": repo["open_issues_count"],      # GitHub counts open PRs here too
        "watchers": repo.get("subscribers_count", ""),
        "size_kb": repo["size"],
        "pushed_at": repo["pushed_at"],
        "latest_release_tag": (release or {}).get("tag_name", ""),
        "latest_release_at": (release or {}).get("published_at", ""),
    }


def read_rows(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def upsert_rows(path: str | Path, new_rows: list[dict]) -> int:
    """Merge rows by (snapshot_date, repo); new rows win. Returns total rows written."""
    merged = {(r["snapshot_date"], r["repo"]): r for r in read_rows(path)}
    for r in new_rows:
        merged[(r["snapshot_date"], r["repo"])] = {k: r.get(k, "") for k in FIELDS}
    rows = [merged[k] for k in sorted(merged)]
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(p)                                   # atomic: never leaves a half-written file
    return len(rows)


def collect(repos=None, path: str = DEFAULT_DATA_PATH, token: str | None = None,
            today: dt.date | None = None, session=None) -> list[dict]:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    session = session or make_session(token or os.environ.get("GITHUB_TOKEN"))
    rows, failures = [], []
    for name in (repos or list(REPOS)):
        try:
            rows.append(fetch_snapshot(session, name, today))
            log.info("collected %s", name)
        except RateLimited:
            raise
        except Exception as exc:                     # one bad repo must not lose the others
            log.warning("skipping %s: %s", name, exc)
            failures.append(name)
    if rows:
        upsert_rows(path, rows)
    if failures:
        log.warning("%d repo(s) failed: %s", len(failures), ", ".join(failures))
    return rows
