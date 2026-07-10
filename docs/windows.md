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
