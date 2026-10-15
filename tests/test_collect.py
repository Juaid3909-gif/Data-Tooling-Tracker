import datetime as dt

import pytest

from tracker.collect import FIELDS, RateLimited, collect, fetch_snapshot, read_rows, upsert_rows

TODAY = dt.date(2026, 9, 30)


class Resp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Routes URLs to canned responses; records calls."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, timeout=None):
        self.calls.append(url)
        for suffix, resp in self.routes.items():
            if url.endswith(suffix):
                return resp
        return Resp(404, {})


def repo_payload(stars=100):
    return {"stargazers_count": stars, "forks_count": 10, "open_issues_count": 5, "subscribers_count": 3,
            "size": 1234, "pushed_at": "2026-09-29T10:00:00Z"}


def test_fetch_snapshot_maps_fields():
    s = FakeSession({"/releases/latest": Resp(200, {"tag_name": "v1.2", "published_at": "2026-09-01T00:00:00Z"}),
                     "/repos/a/b": Resp(200, repo_payload(321))})
    row = fetch_snapshot(s, "a/b", TODAY)
    assert row["stars"] == 321 and row["latest_release_tag"] == "v1.2" and row["snapshot_date"] == "2026-09-30"
    assert set(row) == set(FIELDS)


def test_repo_without_releases_is_ok():
    s = FakeSession({"/releases/latest": Resp(404, {}), "/repos/a/b": Resp(200, repo_payload())})
    row = fetch_snapshot(s, "a/b", TODAY)
    assert row["latest_release_tag"] == "" and row["latest_release_at"] == ""


def test_upsert_is_idempotent_and_replaces_same_day(tmp_path):
    path = tmp_path / "s.csv"
    base = {k: "" for k in FIELDS} | {"snapshot_date": "2026-09-30", "repo": "a/b", "stars": "1"}
    upsert_rows(path, [base])
    upsert_rows(path, [base | {"stars": "2"}])           # same key -> replaced, not duplicated
    upsert_rows(path, [base | {"snapshot_date": "2026-10-01", "stars": "3"}])
    rows = read_rows(path)
    assert [(r["snapshot_date"], r["stars"]) for r in rows] == [("2026-09-30", "2"), ("2026-10-01", "3")]


def test_collect_survives_a_failing_repo(tmp_path):
    s = FakeSession({"/repos/good/repo": Resp(200, repo_payload(50)), "/repos/bad/repo": Resp(500, {}),
                     "/releases/latest": Resp(404, {})})
    rows = collect(repos=["bad/repo", "good/repo"], path=str(tmp_path / "s.csv"), today=TODAY, session=s)
    assert [r["repo"] for r in rows] == ["good/repo"]
    assert [r["repo"] for r in read_rows(tmp_path / "s.csv")] == ["good/repo"]


def test_rate_limit_raises_clear_error(tmp_path):
    limited = Resp(403, {}, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "123"})
    s = FakeSession({"/repos/a/b": limited})
    with pytest.raises(RateLimited, match="GITHUB_TOKEN"):
        collect(repos=["a/b"], path=str(tmp_path / "s.csv"), today=TODAY, session=s)
