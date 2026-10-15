"""CLI:  python -m tracker collect | report | demo"""
from __future__ import annotations

import argparse
import logging

from .config import DEFAULT_DATA_PATH


def main() -> None:
    ap = argparse.ArgumentParser(prog="tracker", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="fetch today's snapshot from the GitHub API")
    c.add_argument("--data", default=DEFAULT_DATA_PATH)

    r = sub.add_parser("report", help="build leaderboard, charts and reports/latest.md")
    r.add_argument("--data", default=DEFAULT_DATA_PATH)
    r.add_argument("--out", default="reports")
    r.add_argument("--title", default="Data tooling tracker")

    d = sub.add_parser("demo", help="write SYNTHETIC history to a separate file for previewing")
    d.add_argument("--data", default="data/demo_snapshots.csv")
    d.add_argument("--days", type=int, default=90)

    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.cmd == "collect":
        from .collect import collect
        rows = collect(path=args.data)
        print(f"Collected {len(rows)} repositories into {args.data}")
    elif args.cmd == "report":
        from .analyze import write_report
        print(f"Wrote {write_report(args.data, args.out, args.title)}")
    else:
        from .demo import make_demo
        n = make_demo(args.data, args.days)
        print(f"Wrote {n} SYNTHETIC rows to {args.data} (do not commit as real data)")


if __name__ == "__main__":
    main()
