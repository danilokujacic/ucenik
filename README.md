# ucenik

## Development

Backend (from repo root, needs the infra in `docker-compose.yaml` running first):

```bash
uv run fastapi dev --reload-dir src
```

`--reload-dir src` matters now that `frontend/` exists alongside `src/` -
without it, `--reload`'s default watch scope is the whole current working
directory, and it would restart the backend on every frontend file save
too. `frontend/node_modules` is already excluded by `watchfiles`' default
ignore list, but `frontend/src`, `frontend/.next`, etc. aren't - scoping the
watch to `src` sidesteps all of it instead of relying on that default.

Frontend (from `frontend/`): see `frontend/README.md`.
