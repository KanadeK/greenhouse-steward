# Sample-data benchmark

The reproducible benchmark command is `python scripts/demo.py`. It processes
the packaged tomato fixture: 672 snapshots over seven days, four metrics per
snapshot, through strict CSV parsing, SQLite storage, rules, anomaly checks,
and trend aggregation. Timing is intentionally recorded by CI artifacts rather
than claimed as a portable hardware number; run the command on the target
machine when selecting hardware capacity.
