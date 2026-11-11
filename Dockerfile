# Fair Measure API image (Fly.io). Serve-time needs only the API stack —
# the training dependencies (pymc, scikit-learn, lightgbm's training extras)
# stay out, which keeps the image a fraction of a full `uv sync`.
#
# The data bundle is baked in: run `just bundle-data` first, which writes the
# column-trimmed marts + model artifacts the API reads to deploy/data/.

FROM python:3.13-slim

# lightgbm needs OpenMP at runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

WORKDIR /app

# Use the image's Python; never let uv fetch its own.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

# Serve-time dependencies only: the `serve` dependency group, installed from
# uv.lock into /app/.venv. `--frozen` uses the locked versions and hashes as
# they are, so the image runs exactly what `just api-smoke` tested.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache --only-group serve

# The package itself, without dependencies (the group above supplies them).
COPY README.md LICENSE ./
COPY src ./src
RUN uv pip install --python .venv/bin/python --no-cache --no-deps .

COPY deploy/data ./data

ENV PATH="/app/.venv/bin:$PATH" \
    PHILLY_DATA_DIR=/app/data \
    PHILLY_ENV=prod \
    PORT=8080

EXPOSE 8080
CMD ["uvicorn", "--factory", "philly_fair_measure.api:create_app", "--host", "0.0.0.0", "--port", "8080"]
