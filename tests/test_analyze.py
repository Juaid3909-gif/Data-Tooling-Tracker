import pandas as pd
import pytest

from tracker.analyze import daily_deltas, leaderboard, write_report
from tracker.collect import FIELDS


def frame(rows):
    base = {k: "" for k in FIELDS} | {"forks": 0, "open_issues": 10, "pushed_at": "2026-09-30T00:00:00Z",
                                      "latest_release_at": "2026-09-20T00:00:00Z", "latest_release_tag": "v1"}
    return pd.DataFrame([base | r for r in rows])


def series(repo, start_date, stars_by_day):
    d0 = pd.Timestamp(start_date)
    return [{"repo": repo, "snapshot_date": (d0 + pd.Timedelta(days=i)).strftime("%Y-%m-%d"), "stars": s}
            for i, s in enumerate(stars_by_day)]


def test_growth_windows_use_correct_baseline():
    # 40 days of data; 100 stars/day for the first 33 days, then 300/day for the last 7
    stars, cur = [], 1000
    for i in range(40):
        cur += 100 if i < 33 else 300
        stars.append(cur)
    board = leaderboard(frame(series("a/x", "2026-08-22", stars)))
    row = board.iloc[0]
    assert row["gain_7d"] == 7 * 300
    assert row["gain_30d"] == stars[-1] - stars[-1 - 30]
    assert row["momentum"] == pytest.approx((2100 / 7) / (row["gain_30d"] / 30), abs=0.01)
    assert row["momentum"] > 1                                        # accelerating


def test_short_history_yields_blank_not_wrong_numbers():
    board = leaderboard(frame(series("a/x", "2026-09-25", [100, 110, 120, 130, 140])))
    row = board.iloc[0]
    assert pd.isna(row["gain_30d"]) and pd.isna(row["gain_7d"])


def test_baseline_picks_latest_snapshot_at_or_before_window_start():
    # missing days: snapshots on day 0, 3, 10 -> for a 7d window from day 10 the baseline is day 3
    df = frame([{"repo": "a/x", "snapshot_date": d, "stars": s}
                for d, s in [("2026-09-01", 100), ("2026-09-04", 130), ("2026-09-11", 200)]])
    row = leaderboard(df).iloc[0]
    assert row["gain_7d"] == 200 - 130


def test_daily_deltas_are_gap_aware():
    df = frame([{"repo": "a/x", "snapshot_date": d, "stars": s}
                for d, s in [("2026-09-01", 100), ("2026-09-02", 110), ("2026-09-05", 140)]])
    d = daily_deltas(df)
    assert pd.isna(d.iloc[0]["star_delta"])
    assert d.iloc[2]["star_delta"] == 30 and d.iloc[2]["gap_days"] == 3
    assert d.iloc[2]["stars_per_day"] == pytest.approx(10.0)          # normalised for the 3-day gap


def test_days_since_push_never_negative():
    df = frame(series("a/x", "2026-09-01", [100] * 3))
    df["pushed_at"] = "2026-09-03T18:00:00Z"                           # later in the day than the snapshot date
    assert leaderboard(df).iloc[0]["days_since_push"] == 0


def test_report_is_written(tmp_path):
    rows = series("a/x", "2026-07-01", [1000 + 10 * i for i in range(60)]) + \
           series("b/y", "2026-07-01", [500 + 5 * i for i in range(60)])
    csv = tmp_path / "s.csv"
    frame(rows).to_csv(csv, index=False)
    out = write_report(csv, tmp_path / "out")
    text = out.read_text()
    assert "Leaderboard" in text and "a/x" in text
    assert (tmp_path / "out" / "growth_indexed.png").exists()
    assert (tmp_path / "out" / "leaderboard.csv").exists()
