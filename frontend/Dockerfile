# syntax=docker/dockerfile:1
# Production image for the Next.js frontend. Built by
# .github/workflows/deploy-frontend.yml with `context: frontend`.
# Relies on `output: "standalone"` in next.config.ts.

# Declared before the first FROM so every stage's FROM can use it. Override
# with --build-arg NODE_VERSION=... (or build.args in compose). Keep in sync
# with node-version in .github/workflows/deploy-frontend.yml.
ARG NODE_VERSION=22

# --- 1. Dependencies ---------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS deps
WORKDIR /app
# pnpm version comes from "packageManager" in package.json.
RUN corepack enable

# Only the manifests, so this layer stays cached until dependencies change.
# pnpm-workspace.yaml carries the allowBuilds settings pnpm install reads.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# --- 2. Build ----------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS build
WORKDIR /app
RUN corepack enable

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* are inlined into the JS bundle at build time, so they have to
# be set here, not when the container starts.
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL} \
    NEXT_TELEMETRY_DISABLED=1

RUN pnpm build

# --- 3. Runtime: just the standalone server ----------------------------------
FROM node:${NODE_VERSION}-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -S app && adduser -S app -G app

# Standalone output has no static assets or public/ in it: copy them in
# alongside server.js, where it expects them.
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public

USER app
EXPOSE 3000

CMD ["node", "server.js"]
