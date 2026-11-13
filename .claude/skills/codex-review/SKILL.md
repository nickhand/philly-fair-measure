---
name: codex-review
description: Run an independent, read-only Codex (gpt-6-astra) review of Philly Fair Measure work from a brief file. Required before a PR that changes a published number, a model input or a flag is called ready; optional for any other change that wants a second model family's read.
---

# Codex review

Codex is this project's second model family. It reviews read-only, with no network, and takes 25 to 45 minutes.

## When

- **Required** before a PR is called ready if it changes a published number (`web/src/data/siteStats.json`, a generated doc block, the screen's counts), a model input (a feature list or a feature mart) or a flag (the screen's flag rules or bands).
- **Optional** for anything else.

## Write the brief

Copy `template.md` from this folder into your scratchpad and fill it in. The brief has three sections and no others:

- `## Material`: what to read. Paths, the diff range, the model runs and marts to measure against.
- `## Question`: what to decide. Ask "is X correct for Y?", not "confirm that X is correct".
- `## Constraints`: optional.

Codex gets the material and the question, never your conclusion. Leave out your diagnosis, your expected answer, your verdict and the PR description's claims of proof. The script refuses a brief with any other heading (any level, indented, or underlined with `===` or `---`), with text before `## Material`, or with Material or Question missing, repeated or empty. A `#` comment line in a code block counts as a heading, so leave comments out of snippets.

## Run

From the checkout under review (the main checkout or a worktree):

```bash
.claude/skills/codex-review/codex-review.sh start <brief.md> <slug>
```

It creates a new run folder (an existing one is refused, so a stale result is never reused), launches Codex detached, and checks it 5 s later. If Codex already stopped with an error, such as a bad model name or a missing login, it exits 1 and prints the end of `codex.log`; otherwise it prints the run folder. Then wait with the Bash tool's `run_in_background: true`, so you are notified when it ends:

```bash
.claude/skills/codex-review/codex-review.sh wait <run-folder>
```

`wait` takes an optional timeout in whole minutes (default 90). It fails when Codex exits non-zero, when its process is gone without an exit code, or when `review.md` has no text. `status <run-folder>` shows progress. Both refuse a folder without `meta.json`. Set `CODEX_REVIEW_MODEL` to use another model.

## Read the result

`review.md` is a claim to check, not a result to relay. For each finding:

1. Reproduce it or refute it yourself, with the `verify-fair-measure` skill.
2. Fix it, dismiss it with a concrete reason, or put it to the owner.

In the PR's `## Verification` section, name the run folder and say what you did with each finding. Never paste Codex's verdict as the PR's proof.

## Where runs live

Each run is a folder `<main checkout>/data/reviews/codex/<UTC stamp>-<slug>/`. It holds `brief.md`, `prompt.md` (the brief with the fixed reviewer preamble), `meta.json` (model, repo, commit, branch, start time), `pid` (the detached process), `codex.log`, `review.md` and `exit.code`. `data/` is gitignored and shared by every worktree. Never commit a run, and never delete one in cleanup.
