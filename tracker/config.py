"""Repositories to track. Edit freely: the pipeline adapts to any list."""

REPOS = {
    # orchestration
    "apache/airflow": "orchestration",
    "dagster-io/dagster": "orchestration",
    "PrefectHQ/prefect": "orchestration",
    # transformation / quality
    "dbt-labs/dbt-core": "transformation",
    "great-expectations/great_expectations": "data quality",
    # processing engines
    "apache/spark": "processing",
    "apache/flink": "processing",
    "pola-rs/polars": "processing",
    "pandas-dev/pandas": "processing",
    "duckdb/duckdb": "processing",
    "trinodb/trino": "processing",
    # storage / table formats
    "apache/iceberg": "storage",
    "delta-io/delta": "storage",
    # ingestion / streaming
    "airbytehq/airbyte": "ingestion",
    "apache/kafka": "ingestion",
}

API_ROOT = "https://api.github.com"
DEFAULT_DATA_PATH = "data/snapshots.csv"
