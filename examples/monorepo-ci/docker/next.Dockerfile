# =============================================================================
#  One Dockerfile for every Next.js app in the monorepo.
#  Build with:  docker build -f docker/next.Dockerfile --build-arg APP=web .
#
#  Requires `output: "standalone"` in each app's next.config.
# =============================================================================

# --- 1. Prune: cut the monorepo down to APP + the packages it depends on -----
FROM node:22-alpine AS prune
ARG APP
WORKDIR /repo
RUN corepack enable
COPY . .
# Produces:
#   out/json/  -> only the package.json files + a pruned pnpm-lock.yaml
#   out/full/  -> only the source of APP and its workspace dependencies
RUN pnpm dlx turbo@2 prune ${APP} --docker

# --- 2. Build ----------------------------------------------------------------
FROM node:22-alpine AS build
ARG APP
WORKDIR /repo
RUN corepack enable

# Install deps first (from package.json files only). This layer stays cached
# until dependencies change, even when source code changes.
COPY --from=prune /repo/out/json/ .
RUN pnpm install --frozen-lockfile

# Now bring in source and build
COPY --from=prune /repo/out/full/ .

# NEXT_PUBLIC_* are inlined into the JS at build time, so they have to be set here
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL} \
    NEXT_TELEMETRY_DISABLED=1

RUN pnpm turbo run build --filter=${APP}

# --- 3. Runtime: just the standalone server, no dev deps, no other apps ------
FROM node:22-alpine AS runtime
ARG APP
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -S app && adduser -S app -G app

# Standalone output keeps the monorepo folder structure (apps/<APP>/server.js)
COPY --from=build --chown=app:app /repo/apps/${APP}/.next/standalone ./
COPY --from=build --chown=app:app /repo/apps/${APP}/.next/static ./apps/${APP}/.next/static
COPY --from=build --chown=app:app /repo/apps/${APP}/public ./apps/${APP}/public

USER app
EXPOSE 3000

# ARG isn't available at runtime, so store the app path in an ENV
ENV APP_DIR=apps/${APP}
CMD ["sh", "-c", "node ${APP_DIR}/server.js"]
