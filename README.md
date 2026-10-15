# Data Tooling Tracker

A **self-updating dataset** of the data-engineering ecosystem. Every day a GitHub Actions job snapshots
15 open-source projects (Airflow, dbt, Spark, DuckDB, Polars, Iceberg, ...), appends to a versioned CSV,
recomputes growth metrics in SQL, and republishes a report with charts, all with no manual steps.

The interesting part is not the code, it's that **the dataset is mine and gets more valuable every day**:
in three months there is a time series that doesn't exist anywhere as a download.

```
GitHub REST API ──► collect.py ──► data/snapshots.csv ──► analyze.py (SQL + pandas) ──► reports/latest.md + charts
      ▲                 idempotent upsert, retries,            window functions,            committed back to the repo
      │                 per-repo fault isolation               gap-aware deltas             by the scheduled workflow
      └──────────── GitHub Actions cron (daily 06:17 UTC) ────────────────────────────────────────────────┘
```

> **Preview:** [`reports/demo/latest.md`](reports/demo/latest.md) shows the output format using **synthetic** data
> (clearly labelled). Real output appears in `reports/latest.md` once the workflow has run for a few weeks.

## Quick start

```bash
python -m pip install -r requirements.txt
make test                       # 11 tests, no network needed
export GITHUB_TOKEN=ghp_...     # optional locally; without it you get 60 API requests/hour (30 needed per run)
make collect                    # appends today's snapshot to data/snapshots.csv
make report                     # writes reports/latest.md, leaderboard.csv, charts
make demo                       # preview with synthetic data, no network
```

To run it yourself in the cloud: fork the repo, enable Actions, and trigger **collect-daily-snapshot**
once from the Actions tab. The workflow uses the built-in `GITHUB_TOKEN`; no secrets to configure.

## What it collects

Per repo per day: stars, forks, open issues (includes open PRs, a GitHub API quirk), size, last push,
latest release tag and date. Edit [`tracker/config.py`](tracker/config.py) to track different projects.

## Metrics

| Metric | Definition |
|---|---|
| `gain_7d`, `gain_30d` | Stars now minus stars on the latest snapshot **at or before** the window start (robust to missed days) |
| `momentum` | 7-day daily star rate / 30-day daily star rate. Above 1 means accelerating |
| `issues_per_1k_stars` | Open issues normalised by popularity, a rough maintenance-load signal |
| `days_since_push`, `days_since_release` | Activity / release-cadence signal |

Growth is computed in SQL ([`tracker/analyze.py`](tracker/analyze.py)): a baseline lookup subquery for the windows and
`LAG() OVER (PARTITION BY repo ORDER BY snapshot_date)` for gap-aware daily rates, run on an in-memory SQLite copy of the CSV.
Short histories yield **blank** cells instead of misleading numbers.

## Engineering decisions

- **CSV as the store.** Diff-friendly in git, no infrastructure, and trivially loadable into any warehouse. At ~15 rows/day
  it stays tiny for years. The trade-off is no concurrent writers; the workflow's `concurrency` group prevents overlap.
- **Idempotent writes.** Rows are keyed by `(snapshot_date, repo)`; re-running a day replaces it, so retries are safe.
  Writes go to a temp file then an atomic rename, so a crash can't corrupt the dataset.
- **Fault isolation.** One failing repo is logged and skipped rather than losing the whole run. A rate-limit
  error is treated differently: it aborts loudly with a fix ("set GITHUB_TOKEN") because continuing is pointless.
- **Retries with backoff** for transient 5xx responses.
- **Tests never touch the network.** The HTTP layer is replaced by a fake session, and the analysis tests use tiny
  hand-computed datasets (including missing days and short history).
- **Synthetic data is quarantined.** `make demo` writes to `data/demo_snapshots.csv` and `reports/demo/` only.

## Known limitations / next steps

- Stars are a popularity proxy, not adoption. Pairing with PyPI/npm download counts would be a natural extension.
- The GitHub API returns *current* totals only, so history starts on the day you first run the job.
- Possible upgrades: load into DuckDB/BigQuery with a dbt model layer, add a Streamlit front-end, and alert on
  anomalous star spikes (bot activity) with a z-score over `stars_per_day`.

## Layout

```
tracker/collect.py    API client, retry/backoff, idempotent CSV upsert
tracker/analyze.py    SQL window logic, leaderboard, charts, markdown report
tracker/demo.py       synthetic history generator (clearly separated)
tracker/__main__.py   CLI: collect | report | demo
tests/                11 tests (fake HTTP session + hand-checked analytics)
.github/workflows/    daily collection + CI
```
