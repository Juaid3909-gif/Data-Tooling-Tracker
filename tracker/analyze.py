"""Turn raw daily snapshots into growth metrics, a leaderboard, and charts.

Growth windows are computed in SQL (window-aware self-joins on an in-memory SQLite copy of the
data) so the logic is readable and testable; pandas handles presentation.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .config import REPOS


def load_snapshots(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["snapshot_date"])
    df["snapshot_date"] = df["snapshot_date"].dt.strftime("%Y-%m-%d")
    return df


def _connect(df: pd.DataFrame) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    df.to_sql("snapshots", conn, index=False)
    conn.execute("CREATE INDEX ix ON snapshots (repo, snapshot_date)")
    return conn


def window_growth_sql(days: int) -> str:
    """For each repo: latest stars vs stars on the most recent snapshot at least `days` days earlier."""
    days = int(days)
    return f"""
    WITH latest AS (
        SELECT repo, MAX(snapshot_date) AS latest_date FROM snapshots GROUP BY repo
    ),
    baseline AS (
        SELECT l.repo, l.latest_date,
               (SELECT MAX(s.snapshot_date) FROM snapshots s
                 WHERE s.repo = l.repo AND s.snapshot_date <= date(l.latest_date, '-{days} day')) AS base_date
        FROM latest l
    )
    SELECT b.repo,
           cur.stars                      AS stars_now,
           old.stars                      AS stars_then,
           cur.stars - old.stars          AS gain_{days}d,
           ROUND(100.0 * (cur.stars - old.stars) / old.stars, 2) AS pct_{days}d,
           cur.forks - old.forks          AS forks_gain_{days}d
    FROM baseline b
    JOIN snapshots cur ON cur.repo = b.repo AND cur.snapshot_date = b.latest_date
    LEFT JOIN snapshots old ON old.repo = b.repo AND old.snapshot_date = b.base_date
    """


def leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    """One row per repo with 7d/30d growth, momentum and health indicators."""
    conn = _connect(df)
    g7 = pd.read_sql(window_growth_sql(7), conn).drop(columns=["stars_then"])
    g30 = pd.read_sql(window_growth_sql(30), conn).drop(columns=["stars_now"])
    out = g7.merge(g30, on="repo", how="left")

    latest = df.sort_values("snapshot_date").groupby("repo").tail(1).set_index("repo")
    out["category"] = out["repo"].map(REPOS).fillna("other")
    out["issues_per_1k_stars"] = (out["repo"].map(latest["open_issues"]) / out["stars_now"] * 1000).round(1)
    ref = pd.Timestamp(df["snapshot_date"].max()) + pd.Timedelta(days=1)   # end of the snapshot day
    pushed = pd.to_datetime(out["repo"].map(latest["pushed_at"]), utc=True).dt.tz_localize(None)
    out["days_since_push"] = (ref - pushed).dt.days
    rel = pd.to_datetime(out["repo"].map(latest["latest_release_at"]), utc=True, errors="coerce").dt.tz_localize(None)
    out["days_since_release"] = (ref - rel).dt.days

    # Momentum: recent daily star rate relative to the 30-day daily rate. >1 means accelerating.
    daily7, daily30 = out["gain_7d"] / 7, out["gain_30d"] / 30
    out["momentum"] = (daily7 / daily30.where(daily30 > 0)).round(2)
    return out.sort_values(["gain_30d", "gain_7d"], ascending=False, na_position="last").reset_index(drop=True)


def daily_deltas(df: pd.DataFrame) -> pd.DataFrame:
    """Daily star gain per repo using LAG(); gap-aware (normalised per elapsed day)."""
    conn = _connect(df)
    return pd.read_sql(
        """
        SELECT repo, snapshot_date,
               stars - LAG(stars) OVER w AS star_delta,
               julianday(snapshot_date) - julianday(LAG(snapshot_date) OVER w) AS gap_days,
               1.0 * (stars - LAG(stars) OVER w)
                   / (julianday(snapshot_date) - julianday(LAG(snapshot_date) OVER w)) AS stars_per_day
        FROM snapshots
        WINDOW w AS (PARTITION BY repo ORDER BY snapshot_date)
        ORDER BY repo, snapshot_date
        """, conn)


def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else (f"{v:,.0f}" if isinstance(v, float) and v.is_integer() else str(v)) for v in r) + " |")
    return "\n".join(lines)


def make_charts(df: pd.DataFrame, board: pd.DataFrame, out_dir: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    # 1) indexed growth: stars rebased to 100 on the first snapshot, so big and small repos compare
    fig, ax = plt.subplots(figsize=(9, 5))
    piv = df.pivot(index="snapshot_date", columns="repo", values="stars")
    piv.index = pd.to_datetime(piv.index)
    indexed = piv / piv.iloc[0] * 100
    top = board.dropna(subset=["gain_30d"]).head(6)["repo"].tolist() or list(indexed.columns[:6])
    for repo in top:
        ax.plot(indexed.index, indexed[repo], label=repo.split("/")[1], linewidth=2)
    ax.set_title("Star growth, indexed to 100 at first snapshot (top movers)")
    ax.set_ylabel("index")
    ax.grid(alpha=.3)
    ax.legend(frameon=False, ncol=2)
    fig.autofmt_xdate()
    fig.tight_layout()
    p = out_dir / "growth_indexed.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    paths.append(p)

    # 2) 30d absolute gain
    b = board.dropna(subset=["gain_30d"]).sort_values("gain_30d")
    if not b.empty:
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.barh(b["repo"].str.split("/").str[1], b["gain_30d"])
        ax.set_title("Stars gained in the last 30 days")
        ax.grid(axis="x", alpha=.3)
        fig.tight_layout()
        p = out_dir / "gain_30d.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(p)
    return paths


def write_report(input_path: str | Path, out_dir: str | Path, title: str = "Data tooling tracker") -> Path:
    df = load_snapshots(input_path)
    out_dir = Path(out_dir)
    board = leaderboard(df)
    charts = make_charts(df, board, out_dir)

    first, last = df["snapshot_date"].min(), df["snapshot_date"].max()
    n_days = df["snapshot_date"].nunique()
    show = board[["repo", "category", "stars_now", "gain_7d", "gain_30d", "pct_30d", "momentum",
                  "issues_per_1k_stars", "days_since_push", "days_since_release"]]
    lines = [f"# {title}", "", f"Snapshots: **{n_days}** days ({first} to {last}), **{df['repo'].nunique()}** repositories.", ""]
    lines += ["## Leaderboard", "", _md_table(show), ""]
    lines += ["*momentum = 7-day daily star rate / 30-day daily star rate (above 1 means accelerating). "
              "Blank growth cells mean the history is shorter than the window.*", ""]
    for c in charts:
        lines += [f"![{c.stem}]({c.name})", ""]
    if board["gain_30d"].notna().any():
        top = board.iloc[0]
        lines += ["## Headline", "",
                  f"- Fastest grower over 30 days: **{top['repo']}** (+{int(top['gain_30d']):,} stars, {top['pct_30d']}%).",
                  ]
        cat = board.dropna(subset=["gain_30d"]).groupby("category")["gain_30d"].sum().sort_values(ascending=False)
        lines.append(f"- Most active category by 30-day star gain: **{cat.index[0]}** (+{int(cat.iloc[0]):,}).")
    report = out_dir / "latest.md"
    report.write_text("\n".join(lines) + "\n")
    board.to_csv(out_dir / "leaderboard.csv", index=False)
    return report
