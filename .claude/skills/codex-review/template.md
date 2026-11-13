## Material

- The change: `git diff origin/main...HEAD` in the working root.
- Code to read: `src/philly_fair_measure/<module>.py`, `tests/test_<module>.py`.
- Data to measure against: `data/marts/<mart>.parquet`, `data/models/run_id=<run>/`.

## Question

1. Does <the change> do <what the PR says it does> for <the population or surface>? Verdict and evidence.
2. Can it change <a published number, a model input, a flag>? Measure it if you can.

## Constraints

- Read-only. Do not rebuild marts or retrain models.
