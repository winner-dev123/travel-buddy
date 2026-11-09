# syntax=docker/dockerfile:1.7
# One image, several process roles (api / realtime / worker / scheduler); see docs/11.

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip wheel --wheel-dir /wheels .

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=build /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels
WORKDIR /srv
COPY alembic.ini ./
COPY migrations ./migrations
USER 10001:10001
EXPOSE 8000
# Migrations run as a separate one-off task: `alembic upgrade head` (docs/11 section 3).
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
