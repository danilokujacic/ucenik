# ucenik frontend

Next.js (App Router) frontend for the `ucenik` API in `src/ucenik/`, built
against `docs/frontend-spec.md`. See that doc for the full backend contract;
this README covers running and orienting yourself in this app specifically.

**One deviation from the spec doc worth knowing**: `docs/frontend-spec.md`
predates four capabilities the live backend actually has - document
download, admin user list/edit/delete, a lecture retry endpoint, and
`GET /users/me/quota`. This app builds against the live API (verified by
reading the route handlers directly), so it includes UI for all four beyond
what the spec doc describes. Each call site is commented with why.

## Stack

- **Next.js 16** (App Router, Turbopack, React 19)
- **TanStack Query v5** - all REST data
- **nuqs** - URL state (lecture detail's Content/Version-history tab)
- **React Context** - auth/session (`lib/auth/auth-context.tsx`)
- Hand-rolled fetch client (`lib/api/client.ts`) - attaches the bearer
  token, retries once on 401 after a silent refresh, normalizes errors
- A fetch+`ReadableStream` SSE reader for Tutor chat (`lib/chat/sse.ts`) -
  `EventSource` can't be used (POST with a body + auth header)
- A native `WebSocket` client for Planner progress
  (`lib/planner/use-planner-socket.ts`) - one connection per plan, `?token=`
  auth, reconnect with backoff, no event replay
- Tailwind CSS v4 + Radix primitives (`components/ui/`) - shadcn-style,
  hand-assembled rather than pulled from the shadcn CLI
- `react-markdown` + `remark-math`/`rehype-katex` for markdown + LaTeX,
  [tikzjax](https://tikzjax.com) (CDN, WASM) for ` ```tikz ` diagram blocks,
  DOMPurify for ` ```svg ` blocks

## Running

```bash
cp .env.example .env.local   # point at your backend, defaults to localhost:8000
pnpm install
pnpm dev
```

Requires the backend running (`uv run fastapi dev` from the repo root, plus
its own infra - see the root `docker-compose.yaml` and `.env.example`) and
at least one admin account provisioned directly against Mongo or via
`POST /admin/users`, since there's no self-service signup (spec §1) - the
very first account has to be created some other way.

```bash
pnpm build   # production build + typecheck
pnpm lint    # eslint
```

## Layout

```
src/
  app/
    login/                       # unauthenticated
    (app)/                       # RequireAuth + nav shell (route group, no URL segment)
      admin/users/                admin only
      subjects/
        [subjectId]/
          documents/ chat/ enrollments/ planner/   teacher/admin/student, gated per spec §2
  components/
    ui/                          # Radix-backed primitives
    <feature>/                   # feature-specific components
  lib/
    api/                         # thin per-resource fetch wrappers + the centralized client
    auth/  chat/  planner/  markdown/  subjects/  query/
    types/api.ts                 # every entity/event shape, spec §4
```

Auth tokens live in `localStorage`, not cookies (spec §1: "the frontend owns
storage"). That means Next's `proxy.ts` (edge, no `localStorage` access)
can't gate routes - `RequireAuth`/`RequireRole`
(`components/auth/guards.tsx`) do that client-side instead. It's UX only;
the server's 401/403/404 responses remain the actual enforcement.

## Not built this pass

- Automated tests (Playwright/RTL)
- Docker/Caddy production wiring - no `frontend` service exists yet in the
  root `docker-compose.prod.yaml`/`Caddyfile`
