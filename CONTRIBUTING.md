# Contributing

Issues and pull requests are welcome. For anything beyond a small fix, please
open an issue first so the approach can be discussed before you invest time.

## Setup

Requires [uv](https://docs.astral.sh/uv/) (Python 3.13) and Node 20+.

```bash
uv sync
npm --prefix web install
```

The data pipeline pulls from public APIs and needs no credentials; see the
README's "Reproducing it" section. The test suite is offline by default (HTTP
is mocked), so code changes can be developed and tested without any data on
disk.

## Quality gates

Everything that CI enforces, in one command:

```bash
just gates
```

That runs `ruff format --check`, `ruff check`, `mypy` (strict mode) on the
Python side, then the Vitest suite and a production build on the web side.
Please run it before opening a pull request. Lint or type errors are fixed,
not suppressed, including pre-existing ones in files you touch.

## Project conventions

- **polars, not pandas.** pandas is deliberately excluded; if a dependency
  would pull it into a code path, it stays out.
- **httpx, not requests**, with tenacity for retries; tests mock HTTP with
  respx.
- **Strict typing.** `mypy --strict` passes on `src/`; new code is typed.
- **No assessment inputs, no demographic inputs.** OPA's assessed values are
  never model features (they are the benchmark), and demographic variables are
  never valuation features (they appear only in after-the-fact equity
  diagnostics). Changes that violate either rule will not be merged.
- **Raw data is immutable.** Snapshots are append-only with manifests;
  corrections happen in the staging layer.
- Commit messages describe what changed and why, plainly.

## Reporting problems with the numbers

If a specific property's estimate or flag looks wrong, an issue with the
parcel number (OPA account number) and what you expected is the most useful
form. Model-level concerns, methodology, calibration, equity, are best filed
as issues referencing the relevant section of [docs/model.md](docs/model.md).
