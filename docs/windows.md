# Windows support

## Supported

- Windows 10/11 + **Docker Desktop with WSL2 backend** (for `runtime=compose`)
- Native Windows Python 3.11+ with **`runtime=local`** (default; recommended for day-to-day training)

## Unsupported

- Docker Desktop Hyper-V legacy backend without WSL2

## Notes

- Prefer `runtime=local` unless you need Postgres/Redis fidelity.
- Episode workspaces live under `%USERPROFILE%\.cascade\episodes`.
- Run `cascade gc` periodically to reclaim disk.
- Line endings: repo uses LF via `.gitattributes`.
- Default `max_parallel_episodes=1` on Desktop-class machines.

## Docker Desktop

If `cascade doctor` reports `docker_daemon not running`, start Docker Desktop or use local runtime:

```powershell
$env:CASCADE_RUNTIME = "local"
uv sync --extra dev
uv run cascade run-episode --agent scripted --task community.T2.pagination_off_by_one.v1
```

### Compose runtime (`runtime=compose`)

1. Start Docker Desktop (WSL2 backend).
2. Pull/build images once:

```powershell
uv run python scripts/pull_images.py
# optional: pin base image digests into scenarios/shopstack/image-pins.env
uv run python scripts/pull_images.py --write-digests
```

3. Run an episode (no fixed host ports; tools use `docker compose exec`):

```powershell
uv run cascade run-episode --runtime compose --agent scripted --task community.T2.pagination_off_by_one.v1
```

4. Reclaim disk (workspaces + labeled compose projects):

```powershell
uv run cascade gc --ttl-hours 2
```

**Notes**

- Episode compose uses an **internal** network (no egress) and bind-mounts the host workspace.
- Ensure Docker Desktop file sharing can access `%USERPROFILE%\.cascade\episodes`.
- Optional debug ports: `$env:CASCADE_COMPOSE_DEBUG = "1"` (single-episode only; refuses if other `cascade_*` projects are active).
- Prefer `runtime=local` for day-to-day agent training; use compose for Postgres/Redis fidelity.