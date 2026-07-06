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

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# serve-time dependencies only (see src/philly_assessments/api.py imports)
RUN uv pip install --system --no-cache \
    "fastapi>=0.115" "uvicorn[standard]>=0.30" "polars>=1.0" \
    "numpy>=2.0" "lightgbm>=4.0" "pydantic>=2.7"

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache --no-deps .

COPY deploy/data ./data

ENV PHILLY_DATA_DIR=/app/data \
    PHILLY_ENV=prod \
    PORT=8080

EXPOSE 8080
CMD ["uvicorn", "--factory", "philly_assessments.api:create_app", "--host", "0.0.0.0", "--port", "8080"]
