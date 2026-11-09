# syntax=docker/dockerfile:1.7
#
# Travel Buddy web image (docs/web/11-deployment.md). Build from the REPOSITORY ROOT:
#   docker build -f apps/web/Dockerfile --build-arg APP_ENV=staging \
#     --build-arg NEXT_PUBLIC_SITE_URL=https://staging.example.com \
#     --build-arg NEXT_PUBLIC_MAP_STYLE_URL=https://tiles.example.com/style.json \
#     -t travelbuddy-web .
#
# APP_ENV has no default on purpose: public pages are prerendered at build time, so a production
# image must be built against the live platform (API_BASE_URL etc. as build secrets/args), never
# against the mock adapter. CI uses APP_ENV=test only to prove the image builds.

ARG NODE_VERSION=24-bookworm-slim

FROM node:${NODE_VERSION} AS deps
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
COPY packages/api-client/package.json packages/api-client/
COPY packages/config/package.json packages/config/
COPY packages/domain-types/package.json packages/domain-types/
COPY packages/i18n/package.json packages/i18n/
COPY packages/ui/package.json packages/ui/
COPY packages/validation/package.json packages/validation/
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

FROM deps AS build
ARG APP_ENV
ARG TB_API_MODE
ARG API_BASE_URL
ARG NEXT_PUBLIC_SITE_URL
ARG NEXT_PUBLIC_MAP_STYLE_URL
ARG NEXT_PUBLIC_MEDIA_HOST
ENV APP_ENV=${APP_ENV} \
    TB_API_MODE=${TB_API_MODE} \
    API_BASE_URL=${API_BASE_URL} \
    NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL} \
    NEXT_PUBLIC_MAP_STYLE_URL=${NEXT_PUBLIC_MAP_STYLE_URL} \
    NEXT_PUBLIC_MEDIA_HOST=${NEXT_PUBLIC_MEDIA_HOST} \
    NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN test -n "$APP_ENV" || (echo "APP_ENV build arg is required (test|staging|production)" && exit 1)
# Secrets needed only at build time (e.g. SESSION_SECRET, OIDC_*) are mounted, never baked in.
RUN --mount=type=secret,id=web_env,required=false \
    sh -c 'if [ -f /run/secrets/web_env ]; then set -a; . /run/secrets/web_env; set +a; fi; npm run build -w @travelbuddy/web'

FROM node:${NODE_VERSION} AS runner
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1
# Next.js standalone output mirrors the monorepo layout (outputFileTracingRoot = repo root).
COPY --from=build --chown=node:node /repo/apps/web/.next/standalone ./
COPY --from=build --chown=node:node /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=node:node /repo/apps/web/public ./apps/web/public
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "apps/web/server.js"]
