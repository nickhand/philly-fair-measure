# CI and workflow changes

Two GitHub workflows run this repository. `.github/workflows/ci.yml` routes each push or pull request by changed paths (`.github/ci/scope.py`), runs the Python job (ruff, ty, pytest, `sync-docs --check`) and the web job (npm ci, audit, unit and worker tests, build, Cloudflare staging dry run, production build), then a quality gate, and on `main` deploys the web artifact to Cloudflare through the protected `frontend-production` environment. `.github/workflows/snapshot.yml` runs weekly, pulls the previous snapshots from S3 through OIDC, captures fresh CARTO tables, uploads them, and commits a diff summary to `docs/snapshots/`. The contract tests in `.github/ci/` pin the routing and the release mechanics.

## Sub-features

- `ci-routing` maps changed paths to `python=`, `web=`, `release=` (fails closed to all true on empty input).
- `ci-release-contracts` keeps production deploys inside the guarded workflow, reruns reusing one candidate, polled activation and rollback, and the hydrated-browser release check (`test_release_contracts.py`).
- `ci-python-job` and `ci-web-job` run the same commands as `just gates` plus `npm audit`, the staging dry run and the production build.
- `ci-deploy` publishes the validated artifact, verifies it live, and rolls back on failure.
- `snapshot-weekly` captures `opa_properties_public` and `assessments`, syncs with S3, and commits `docs/snapshots/<date>.md`.

## How to get to it (user POV)

- A contributor opens a pull request or pushes to `main`; the checks appear on the PR.
- The owner dispatches `CI` with `deploy_production` from the Actions tab.
- The schedule fires `snapshot` on Mondays at 04:23 UTC, or the owner dispatches it.

## Driving it with fm-verify

Preconditions:

- Run from the checkout under test. Commit the change, or leave it in the working tree; `$S ci` includes committed, staged, unstaged and untracked paths.

- **Contracts, routing, syntax.** Run `$S ci <slug>` (or `$S ci <slug> <base>` for a branch not based on `origin/main`). It saves `ci.txt` and exits 0 when the `.github/ci` unittest run passes (11 tests at `ae7a681`), prints the changed paths with the `python=`, `web=`, `release=` routing CI would choose, and parses every file in `.github/workflows/` with PyYAML. Check the routing matches your intent: a `web/src` change must say `release=true`; a docs-only web change (`web/README.md`, `web/tests/`) must say `release=false`.
- **Routing rule change.** When `scope.py` changes, add or update a case in `.github/ci/test_scope.py` and pipe sample paths by hand: `printf 'web/src/App.vue\ndocs/frontend.md\n' | python3 .github/ci/scope.py`.
- **Job commands.** Run what the changed job runs. Python job: `just gates` covers ruff, ty, pytest and `sync-docs --check`. Web job: `just gates` covers unit tests, worker tests and `npm run build`; add `npm --prefix web run build:cloudflare:production` (local, replaces `web/dist`) and `npm --prefix web audit --omit=dev --audit-level=high` (queries the npm registry). Tee each into the evidence folder.
- **Snapshot workflow.** Locally only the YAML parse and the commands' arguments can be checked: `$S cli <slug> snapshot-all-help snapshot-all --help` and `$S cli <slug> snapshot-diff snapshot-diff --datasets assessments --out "$($S evidence <slug>)/snapshot-diff.md"`. The local lake holds one `assessments` snapshot (`20260702T182943Z`), so the diff prints `nothing to diff`; the series lives in S3.
- **Report.** List as unverified everything in the next paragraph that your change touches.

What only a real GitHub run proves: `${{ }}` expression evaluation and `if:` conditions, `needs` wiring and job outputs, the `concurrency` queue, runner images and pinned action SHAs resolving, `GITHUB_OUTPUT` and `RUNNER_TEMP` handling, the `frontend-production` environment's protection rules and secrets, Cloudflare upload, activation and rollback, the OIDC role and S3 sync in `snapshot.yml`, the schedule trigger, and the bot's push to `main`.

## Gotchas

- `scope.py` answers true for all three on empty input. `$S ci` avoids that by including the working tree; a bare `git diff origin/main...HEAD | python3 .github/ci/scope.py` before the first commit does not.
- The contract tests assert literal strings in `ci.yml` and `web/package.json`. Renaming a step or a script breaks them on purpose; update the test with the change, never delete the assertion to pass.
- actionlint is not installed here. A YAML parse catches indentation and quoting errors only.
- `just snapshot-current` and `fair-measure snapshot-all` write new raw snapshots into the shared lake. They are pipeline runs, not checks.
- `npm run dry-run:cloudflare:staging` runs wrangler, which this skill has not observed offline; treat it as needing the network and say so if you run it.
