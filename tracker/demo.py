"""Generate SYNTHETIC history so charts/reports can be previewed before real data accumulates.

The output is written to a separate file and clearly labelled. Never mix it with real snapshots.
"""
from __future__ import annotations

import datetime as dt
import random

from .collect import FIELDS, upsert_rows
from .config import REPOS

START_STARS = {"apache/airflow": 38000, "dagster-io/dagster": 11000, "PrefectHQ/prefect": 16000, "dbt-labs/dbt-core": 9500,
               "great-expectations/great_expectations": 10000, "apache/spark": 39000, "apache/flink": 24000,
               "pola-rs/polars": 29000, "pandas-dev/pandas": 43000, "duckdb/duckdb": 22000, "trinodb/trino": 10000,
               "apache/iceberg": 6000, "delta-io/delta": 7000, "airbytehq/airbyte": 15000, "apache/kafka": 28000}


def make_demo(path: str, days: int = 90, seed: int = 1, end: dt.date | None = None) -> int:
    rng = random.Random(seed)
    end = end or dt.date(2026, 9, 30)
    rows = []
    for repo in REPOS:
        stars = START_STARS.get(repo, 5000)
        rate = stars * rng.uniform(0.0002, 0.0012)                    # daily growth proportional to size
        forks, issues = int(stars * 0.25), int(stars * 0.03)
        for i in range(days):
            d = end - dt.timedelta(days=days - 1 - i)
            trend = 1 + (0.6 * rng.random() if repo.endswith(("polars", "duckdb", "iceberg")) and i > days * 0.6 else 0)
            stars += max(0, int(rng.gauss(rate * trend, rate * 0.4)))
            forks += rng.randint(0, 3)
            issues = max(0, issues + rng.randint(-4, 5))
            rows.append({
                "snapshot_date": d.isoformat(), "repo": repo, "stars": stars, "forks": forks, "open_issues": issues,
                "watchers": "", "size_kb": 100000 + i * 40,
                "pushed_at": f"{d.isoformat()}T{rng.randint(0, 23):02d}:15:00Z",
                "latest_release_tag": "v-demo",
                "latest_release_at": f"{(d - dt.timedelta(days=rng.randint(2, 40))).isoformat()}T12:00:00Z",
            })
    return upsert_rows(path, rows)
