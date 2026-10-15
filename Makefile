.PHONY: install test collect report demo
install:
	python -m pip install -r requirements.txt
test:
	python -m pytest -q
collect:            # needs network; export GITHUB_TOKEN for a higher rate limit
	python -m tracker collect
report:
	python -m tracker report
demo:               # SYNTHETIC data, for previewing the report
	python -m tracker demo
	python -m tracker report --data data/demo_snapshots.csv --out reports/demo --title "Data tooling tracker (SYNTHETIC DEMO DATA)"
