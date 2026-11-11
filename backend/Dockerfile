# syntax=docker/dockerfile:1.7
# One image, several process roles (api / realtime / worker / scheduler); see docs/11.

FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY app ./app
# The `gcp` extra adds the Cloud SQL connector (ADR-0028).
RUN pip wheel --wheel-dir /wheels ".[gcp]"

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
COPY --from=build /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels
# DB-IP "IP to City Lite" (CC BY 4.0) behind the Companions map's approximate starting point
# (LOC-010, ADR-0030). It is fetched again whenever this layer rebuilds, which is every code
# change. If the download fails the image is built without it, and the API asks travellers to
# choose a city instead.
RUN python -m app.modules.location.fetch_ip_database /srv/geo/dbip-city-lite.mmdb     || echo "warning: built without the IP geolocation database"
ENV IP_GEOLOCATION_DB=/srv/geo/dbip-city-lite.mmdb
WORKDIR /srv
COPY alembic.ini ./
COPY migrations ./migrations
USER 10001:10001
EXPOSE 8000
# Migrations run as a separate one-off task: `alembic upgrade head` (docs/11 section 3).
# PORT is injected by the platform (Railway sets it); proxy headers are trusted because the
# container is only reachable through the platform's load balancer.
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --no-server-header"]
