set shell := ["bash", "-c"]
set dotenv-load := true

# Show available recipes
[private]
default:
	@just --list

# ---------------------------------------------------------------- dev

# Launch the API and web dev servers together (kills stale processes first)
[group: "dev"]
dev:
	-lsof -ti:8000 | xargs kill -9 2>/dev/null || true
	-lsof -ti:5173 | xargs kill -9 2>/dev/null || true
	@just api & just web

# Run the Python API in development mode
[group: "dev"]
api:
	uv run fair-measure api

# Run the web dev server
[group: "dev"]
web:
	cd web && npm run dev

# ---------------------------------------------------------------- quality

# Every gate: ruff (check + format), mypy, pytest, web tests, typed build
[group: "quality"]
gates:
	uv run ruff format --check src tests
	uv run ruff check src tests
	uv run mypy src
	uv run fair-measure sync-docs --check
	uv run pytest -q
	cd web && npm run test:unit -- --run
	cd web && npm run build

# Python tests only
[group: "quality"]
test:
	uv run pytest -q

# ---------------------------------------------------------------- pipeline

# Full coherent retrain: features -> every model -> screen -> site stats.
# Any feature/mart rebuild REQUIRES retraining every model (the screen
# refuses stale runs) — this is the one command that keeps it all coherent.
[group: "pipeline"]
retrain-all:
	uv run fair-measure build-features
	uv run fair-measure build-condo-features
	uv run fair-measure train-baseline
	uv run fair-measure train-baseline --market retail
	uv run fair-measure train-bayesian
	uv run fair-measure train-condo
	uv run fair-measure screen-assessments
	uv run fair-measure export-web-stats

# Rebuild the screen + regenerate the site's stats (models unchanged)
[group: "pipeline"]
rescreen:
	uv run fair-measure screen-assessments
	uv run fair-measure export-web-stats

# Regenerate web/src/data/siteStats.json from the latest runs
[group: "pipeline"]
export-stats:
	uv run fair-measure export-web-stats
	uv run fair-measure sync-docs

# ---------------------------------------------------------------- deploy: api (Fly.io)

# Assemble deploy/data — the column-trimmed marts + model artifacts the API
# serves from (baked into the Docker image)
[group: "deploy-api"]
bundle-data:
	uv run python scripts/bundle_deploy_data.py

# Boot the API against the deploy bundle and exercise every endpoint, in a
# venv holding ONLY the serve deps (mirrors the Docker image) — catches both
# missing bundle files and training-only imports leaking into the serve path
[group: "deploy-api"]
api-smoke:
	rm -rf .venv-serve
	uv venv .venv-serve
	uv pip install --python .venv-serve/bin/python -r requirements.serve.txt httpx
	uv pip install --python .venv-serve/bin/python --no-deps .
	.venv-serve/bin/python scripts/smoke_api.py

# Ship the API: bundle, smoke-test, then deploy to Fly.io
[group: "deploy-api"]
fly-deploy: bundle-data api-smoke
	flyctl deploy

# One-time Fly.io app setup (run once, then fly-secrets + fly-deploy)
[group: "deploy-api"]
fly-launch:
	flyctl launch --no-deploy --copy-config

# Set the admin token secret (generate one first, e.g. `openssl rand -hex 24`)
[group: "deploy-api"]
fly-secrets:
	flyctl secrets set PHILLY_ADMIN_TOKEN="{{ env('PHILLY_ADMIN_TOKEN') }}"

[group: "deploy-api"]
fly-status:
	flyctl status

[group: "deploy-api"]
fly-logs:
	flyctl logs

[group: "deploy-api"]
fly-ssh:
	flyctl ssh console

# ---------------------------------------------------------------- deploy: web (Netlify)

# Production build exactly as Netlify runs it (subpath base + Fly API URL)
[group: "deploy-web"]
web-build-prod:
	cd web && VITE_PUBLIC_BASE="/fair-measure/" VITE_API_BASE="https://fair-measure-api.fly.dev" npm run build

# Deploy a preview to Netlify from the local prod build
[group: "deploy-web"]
netlify-preview: web-build-prod
	cd web && npx netlify deploy --dir=dist

# Deploy the site to production. Pushes to main also auto-build once the
# repo is linked in the Netlify UI; this is the manual path.
[group: "deploy-web"]
netlify-deploy: web-build-prod
	cd web && npx netlify deploy --dir=dist --prod
