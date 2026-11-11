#!/usr/bin/env bash
# Independent read-only Codex review from a brief file. See SKILL.md beside this file.
#
#   codex-review.sh start <brief.md> <slug>      launch detached; prints the run folder
#   codex-review.sh wait <run-folder> [minutes]  block until done (default 90 min)
#   codex-review.sh status <run-folder>
set -euo pipefail

MODEL="${CODEX_REVIEW_MODEL:-gpt-6-astra}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "codex-review: $*" >&2; exit 2; }

main_checkout() {
  local common
  common="$(git rev-parse --path-format=absolute --git-common-dir)" || die "not inside a git checkout"
  dirname "$common"
}

check_brief() {
  local brief="$1" bad
  grep -qx '## Material' "$brief" || die "$brief has no '## Material' section (copy $HERE/template.md)"
  grep -qx '## Question' "$brief" || die "$brief has no '## Question' section (copy $HERE/template.md)"
  bad="$(grep -E '^## ' "$brief" | grep -vxE '## (Material|Question|Constraints)' || true)"
  [[ -z "$bad" ]] || die "$brief has sections Codex must not get: $bad. A brief holds only Material, Question and Constraints, never the lead's findings or conclusion."
}

cmd_start() {
  local brief="${1:-}" slug="${2:-}"
  [[ -f "$brief" ]] || die "usage: codex-review.sh start <brief.md> <slug>"
  [[ "$slug" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "slug must be lowercase letters, digits and hyphens"
  command -v codex >/dev/null || die "codex CLI not on PATH"
  check_brief "$brief"

  local repo main sha branch run python
  repo="$(git rev-parse --show-toplevel)"
  main="$(main_checkout)"
  sha="$(git -C "$repo" rev-parse HEAD)"
  branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD)"
  run="${CODEX_REVIEW_DIR:-$main/data/reviews/codex}/$(date -u +%Y%m%dT%H%M%SZ)-$slug"
  python="$main/.venv/bin/python"
  mkdir -p "$run"
  cp "$brief" "$run/brief.md"

  cat > "$run/prompt.md" <<EOF
You are an independent reviewer for Philly Fair Measure, an open-data check of
Philadelphia property assessments. Another agent did the work under review. You
have not seen its reasoning, on purpose: form your own view from the material.

Environment:
- Working root: $repo at commit $sha (branch $branch).
- Project instructions: $main/AGENTS.md. Read it first.
- The data lake is $main/data (marts in data/marts, model runs in data/models/run_id=*).
- The sandbox is read-only and has no network. For measurements use
  $python (polars is installed); \`uv run\` may fail because it writes a cache.

For every claim you make:
- cite file:line, or the command you ran and what it printed;
- label it measured (you ran it), read (you saw it in code or docs) or inferred;
- where the question asks for a verdict, answer confirmed, partly, refuted or
  could not verify, and say why.
Put problems the question did not ask about in a last section, "Outside the
question". Write the final answer as Markdown. Do not modify any file.

---

EOF
  cat "$brief" >> "$run/prompt.md"

  cat > "$run/meta.json" <<EOF
{"model": "$MODEL", "repo": "$repo", "commit": "$sha", "branch": "$branch",
 "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "brief_sha256": "$(shasum -a 256 "$brief" | cut -d' ' -f1)"}
EOF

  nohup sh -c 'codex exec -m "$1" -s read-only -C "$2" -o "$3/review.md" - < "$3/prompt.md" > "$3/codex.log" 2>&1; echo $? > "$3/exit.code"' \
    sh "$MODEL" "$repo" "$run" > /dev/null 2>&1 &
  echo "$run"
}

cmd_wait() {
  local run="${1:-}" minutes="${2:-90}" waited=0
  [[ -d "$run" ]] || die "usage: codex-review.sh wait <run-folder> [minutes]"
  until [[ -f "$run/exit.code" ]]; do
    (( waited < minutes * 60 )) || die "no result after $minutes min; see $run/codex.log"
    sleep 30
    waited=$((waited + 30))
  done
  local code
  code="$(cat "$run/exit.code")"
  [[ "$code" == 0 ]] || die "codex exited $code; see $run/codex.log"
  [[ -s "$run/review.md" ]] || die "codex exited 0 but wrote no review; see $run/codex.log"
  echo "done after ${waited}s of waiting: $run/review.md ($(wc -l < "$run/review.md") lines)"
}

cmd_status() {
  local run="${1:-}"
  [[ -d "$run" ]] || die "usage: codex-review.sh status <run-folder>"
  if [[ -f "$run/exit.code" ]]; then
    echo "finished, exit $(cat "$run/exit.code")"
  else
    echo "running since $(sed -n 's/.*"started_at": "\([^"]*\)".*/\1/p' "$run/meta.json")"
  fi
  tail -n 5 "$run/codex.log" 2>/dev/null || true
}

case "${1:-}" in
  start) shift; cmd_start "$@" ;;
  wait) shift; cmd_wait "$@" ;;
  status) shift; cmd_status "$@" ;;
  *) die "usage: codex-review.sh start <brief.md> <slug> | wait <run-folder> [minutes] | status <run-folder>" ;;
esac
