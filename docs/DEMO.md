# Deterministic demo

Run `make demo` (or `python scripts/demo.py`) from the repository root. It
imports the packaged `tomato-7d` CSV through the production application facade
and writes `artifacts/tomato-7d-report.json`. The output is generated at run
time and includes persisted rule evidence, watering safety, and trends.

For the interactive view, run `greenhouse-steward serve --db artifacts/demo.sqlite3`
and open the loopback dashboard. Do not treat the simulated relay as hardware
control.
