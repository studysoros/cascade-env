"""cascade CLI: doctor | gc | list-tasks | run-episode | eval-baselines | serve."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from cascade_env.config import get_config
from cascade_env.version import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cascade",
        description="Cascade production systems RL environment CLI",
    )
    parser.add_argument("--version", action="version", version=f"cascade {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="Check local prerequisites")
    p_gc = sub.add_parser("gc", help="Garbage-collect stale episode workspaces")
    p_gc.add_argument("--ttl-hours", type=float, default=2.0)
    p_gc.add_argument("--dry-run", action="store_true")

    p_list = sub.add_parser("list-tasks", help="List tasks in a pack")
    p_list.add_argument("--pack", default="community")

    p_run = sub.add_parser("run-episode", help="Run a scripted or interactive episode")
    p_run.add_argument("--pack", default="community")
    p_run.add_argument("--task", default=None)
    p_run.add_argument("--seed", type=int, default=0)
    p_run.add_argument("--runtime", default="local", choices=["local", "compose"])
    p_run.add_argument(
        "--agent",
        default="scripted",
        choices=["scripted", "random", "manual", "llm"],
        help="scripted=known-fix; random=noop; manual=stdin; llm=real model (API key)",
    )
    p_run.add_argument("--max-steps", type=int, default=40)
    p_run.add_argument("--provider", default=None, help="LLM provider (openai|anthropic|xai)")
    p_run.add_argument("--model", default=None, help="LLM model id")
    p_run.add_argument("--base-url", default=None, help="LLM API base URL")
    p_run.add_argument("--api-key", default=None, help="LLM API key (else env)")
    p_run.add_argument("--temperature", type=float, default=0.0)

    p_eval = sub.add_parser(
        "eval-baselines",
        help="Run N seeds × task set; write JSON pass-rate summary",
    )
    p_eval.add_argument("--agent", choices=["scripted", "llm"], default="scripted")
    p_eval.add_argument("--pack", default="community")
    p_eval.add_argument("--runtime", default="local", choices=["local", "compose"])
    p_eval.add_argument("--max-steps", type=int, default=40)
    p_eval.add_argument(
        "--tasks",
        default=None,
        help="Comma-separated task ids (default: community T1–T5)",
    )
    p_eval.add_argument("--seeds", default="0", help="Comma-separated seeds")
    p_eval.add_argument("--provider", default=None)
    p_eval.add_argument("--model", default=None)
    p_eval.add_argument("--base-url", default=None)
    p_eval.add_argument("--api-key", default=None)
    p_eval.add_argument("--temperature", type=float, default=0.0)
    p_eval.add_argument(
        "--out",
        default="docs/artifacts/baseline-summary.json",
        help="JSON summary output path",
    )
    p_eval.add_argument("--md-out", default=None, help="Optional markdown table path")
    p_eval.add_argument("--quiet", action="store_true")

    p_serve = sub.add_parser(
        "serve",
        help="Start HTTP rollout server (remote trainers; requires API key)",
    )
    p_serve.add_argument(
        "--host",
        default=None,
        help="Bind host (default: CASCADE_SERVER_HOST or 127.0.0.1)",
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (default: CASCADE_SERVER_PORT or 8765)",
    )
    p_serve.add_argument(
        "--api-key",
        default=None,
        help="Server API key (default: CASCADE_SERVER_API_KEY; auto-generated if unset)",
    )
    p_serve.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
    )

    args = parser.parse_args(argv)
    if args.cmd == "doctor":
        return cmd_doctor()
    if args.cmd == "gc":
        return cmd_gc(args.ttl_hours, args.dry_run)
    if args.cmd == "list-tasks":
        return cmd_list_tasks(args.pack)
    if args.cmd == "run-episode":
        return cmd_run_episode(args)
    if args.cmd == "eval-baselines":
        return cmd_eval_baselines(args)
    if args.cmd == "serve":
        return cmd_serve(args)
    return 1


def cmd_doctor() -> int:
    cfg = get_config()
    print(f"cascade {__version__}")
    print(f"python      {sys.version.split()[0]}")
    print(f"data_root   {cfg.resolved_data_root()}")
    print(f"work_root   {cfg.resolved_work_root()}")
    print(f"scenarios   {cfg.scenarios_dir()} exists={cfg.scenarios_dir().is_dir()}")
    print(f"packs       {cfg.packs_dir()} exists={cfg.packs_dir().is_dir()}")
    compose = cfg.scenarios_dir() / "shopstack" / "docker-compose.yml"
    print(f"compose     {compose} exists={compose.is_file()}")
    pins = cfg.scenarios_dir() / "shopstack" / "image-pins.env"
    print(f"image_pins  {pins} exists={pins.is_file()}")
    extra = cfg.extra_pack_dirs()
    if extra:
        for p in extra:
            print(f"extra_pack  {p} exists={p.is_dir()} pack_yaml={(p / 'pack.yaml').exists()}")
    else:
        print("extra_pack  (none — set CASCADE_EXTRA_PACKS or CASCADE_HOLDOUT_DIR for sealed packs)")

    docker_bin = shutil.which(cfg.docker_bin) or shutil.which("docker")
    print(f"docker_bin  {bool(docker_bin)} path={docker_bin or ''}")
    daemon_ok = False
    if docker_bin:
        import subprocess

        try:
            r = subprocess.run(
                [docker_bin, "info"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            daemon_ok = r.returncode == 0
            print(f"docker_daemon {'ok' if daemon_ok else 'not running'}")
        except Exception as exc:  # noqa: BLE001
            print(f"docker_daemon error: {exc}")
        try:
            r = subprocess.run(
                [docker_bin, "compose", "version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            ver = (r.stdout or r.stderr or "").strip().splitlines()[:1]
            print(f"compose     {'ok' if r.returncode == 0 else 'missing'} {ver[0] if ver else ''}")
        except Exception as exc:  # noqa: BLE001
            print(f"compose     error: {exc}")

    if daemon_ok:
        from cascade_env.runtime.compose import ComposeRuntimeBackend

        backend = ComposeRuntimeBackend()
        img = backend.image_pins_status()
        for image, present in (img.get("present") or {}).items():
            print(f"image       {image} present={present}")
        projects = backend.list_cascade_projects()
        print(f"compose_projects {len(projects)} {projects[:5]}")
        missing_base = [
            image
            for key, image in (img.get("pins") or {}).items()
            if key in ("CASCADE_POSTGRES_IMAGE", "CASCADE_REDIS_IMAGE")
            and not (img.get("present") or {}).get(image)
        ]
        if missing_base:
            print(
                "hint        base images missing — run: "
                "uv run python scripts/pull_images.py"
            )

    # orphan workspaces
    root = cfg.resolved_work_root()
    orphans = list(root.glob("ep_*")) if root.is_dir() else []
    print(f"orphan_eps  {len(orphans)}")
    print(f"runtime_default {cfg.runtime} (CASCADE_RUNTIME=local|compose)")
    print(
        f"http_server  enable={cfg.enable_http_server} "
        f"bind={cfg.server_host}:{cfg.server_port} "
        f"api_key_set={bool(cfg.server_api_key)} "
        f"(cascade serve)"
    )
    print("SANDBOX ONLY — never attach tools to real production credentials.")
    return 0


def cmd_gc(ttl_hours: float, dry_run: bool) -> int:
    cfg = get_config()
    root = cfg.resolved_work_root()
    cutoff = time.time() - ttl_hours * 3600
    removed = 0
    if root.is_dir():
        for p in root.glob("ep_*"):
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                print(f"{'would remove' if dry_run else 'removing'} {p}")
                if not dry_run:
                    shutil.rmtree(p, ignore_errors=True)
                removed += 1
    else:
        print("no episode work_root yet")

    # Docker compose project reaper (labeled resources)
    docker_projects = 0
    if shutil.which(cfg.docker_bin) or shutil.which("docker"):
        try:
            from cascade_env.runtime.compose import ComposeRuntimeBackend

            backend = ComposeRuntimeBackend()
            if backend.daemon_ok():
                gone = backend.gc_projects(
                    older_than_s=ttl_hours * 3600,
                    dry_run=dry_run,
                )
                for name in gone:
                    print(f"{'would remove compose' if dry_run else 'removing compose'} {name}")
                docker_projects = len(gone)
        except Exception as exc:  # noqa: BLE001
            print(f"compose gc skipped: {exc}")

    print(f"gc complete: {removed} episode dirs, {docker_projects} compose projects")
    return 0


def cmd_list_tasks(pack: str) -> int:
    from cascade_env.tasks.loader import TaskLoader

    loader = TaskLoader()
    for stem in loader.list_tasks(pack):
        task = loader.load_task(pack, stem)
        print(f"{task.id:50} family={task.family:16} tier={task.tier}")
    return 0


def cmd_run_episode(args: argparse.Namespace) -> int:
    from cascade_env.env import CascadeEnv
    from cascade_env.agents.scripted import scripted_policy

    if args.agent == "llm":
        return _cmd_run_episode_llm(args)

    env = CascadeEnv(
        pack=args.pack,
        task_id=args.task,
        runtime=args.runtime,
        seed=args.seed,
        max_steps=args.max_steps,
    )
    try:
        obs_s, info = env.reset(seed=args.seed)
        obs = json.loads(obs_s)
        print(f"episode={info['episode_id']} task={obs['task']['id']}")
        print(f"title: {obs['task']['title']}")
        terminated = truncated = False
        total_r = 0.0
        while not (terminated or truncated):
            if args.agent == "scripted":
                action = scripted_policy(obs, info)
            elif args.agent == "manual":
                line = input("action JSON> ").strip()
                action = json.loads(line)
            else:
                action = {"tool": "services.ps", "args": {}}
            obs_s, reward, terminated, truncated, info = env.step(action)
            total_r += float(reward)
            obs = json.loads(obs_s)
            tr = info.get("tool_result") or {}
            print(
                f"step={obs['step']} tool={action.get('tool')} "
                f"r={reward:.4f} ok={tr.get('ok')} term={terminated} trunc={truncated}"
            )
        print(
            json.dumps(
                {
                    "success": info.get("success"),
                    "terminal_reward": info.get("terminal_reward", total_r),
                    "total_step_reward": total_r,
                    "trajectory": info.get("trajectory_path"),
                    "verifiers": {
                        v["id"]: v["passed"] for v in info.get("verifiers", [])
                    },
                },
                indent=2,
            )
        )
        return 0 if info.get("success") else 2
    finally:
        env.close()


def _cmd_run_episode_llm(args: argparse.Namespace) -> int:
    import gymnasium as gym

    import cascade_env
    from cascade_env.agents.llm_agent import run_llm_episode
    from cascade_env.agents.llm_client import LLMClient, LLMError

    cascade_env.register_envs()
    try:
        client = LLMClient(
            provider=args.provider,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
            temperature=args.temperature,
        )
        client.require_api_key()
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    env = gym.make(
        "Cascade-v0",
        pack=args.pack,
        runtime=args.runtime,
        task_id=args.task,
        max_steps=args.max_steps,
    )
    try:
        print(f"provider={client.provider} model={client.model}")
        outcome = run_llm_episode(
            env,
            client,
            seed=args.seed,
            task_id=args.task,
            verbose=True,
        )
        print(json.dumps(outcome.as_dict(), indent=2, ensure_ascii=False))
        return 0 if outcome.success and not outcome.error else 2
    finally:
        env.close()
        client.close()


def cmd_serve(args: argparse.Namespace) -> int:
    """Start FastAPI rollout server (create / step / close episodes over HTTP).

    Invoking ``cascade serve`` opts in to the HTTP server feature flag.
    """
    from cascade_env.server.auth import generate_api_key
    from cascade_env.server.app import run_server

    cfg = get_config()
    api_key = (args.api_key or cfg.server_api_key or "").strip()
    generated = False
    if not api_key:
        api_key = generate_api_key()
        generated = True

    host = args.host or cfg.server_host
    port = int(args.port if args.port is not None else cfg.server_port)
    cfg = cfg.model_copy(
        update={
            "enable_http_server": True,
            "server_api_key": api_key,
            "server_host": host,
            "server_port": port,
        }
    )

    print(f"cascade serve  version={__version__}")
    print(f"  bind         http://{host}:{port}")
    print(f"  openapi      http://{host}:{port}/docs")
    print(f"  health       http://{host}:{port}/health")
    if generated:
        print(f"  api_key      {api_key}  (generated — set CASCADE_SERVER_API_KEY to pin)")
    else:
        print("  api_key      (from --api-key or CASCADE_SERVER_API_KEY)")
    print("  auth         X-API-Key or Authorization: Bearer")
    print("  SANDBOX ONLY — never attach tools to real production credentials.")
    print("  Example client: uv run python examples/remote_client.py")

    try:
        run_server(host=host, port=port, api_key=api_key, config=cfg, log_level=args.log_level)
    except KeyboardInterrupt:
        print("\nshutting down")
        return 0
    return 0


def cmd_eval_baselines(args: argparse.Namespace) -> int:
    from cascade_env.agents.eval import (
        DEFAULT_BASELINE_TASKS,
        EvalConfig,
        format_markdown_table,
        run_eval,
        write_summary,
    )
    from cascade_env.agents.llm_client import LLMError

    def _tasks(raw: str | None) -> list[str]:
        if not raw or not raw.strip():
            return list(DEFAULT_BASELINE_TASKS)
        return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]

    def _seeds(raw: str) -> list[int]:
        return [int(p.strip()) for p in raw.replace(";", ",").split(",") if p.strip()]

    cfg = EvalConfig(
        tasks=_tasks(args.tasks),
        seeds=_seeds(args.seeds),
        pack=args.pack,
        runtime=args.runtime,
        max_steps=args.max_steps,
        agent=args.agent,
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        base_url=args.base_url,
        temperature=args.temperature,
        verbose=not args.quiet,
    )
    try:
        summary = run_eval(cfg)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out = write_summary(summary, args.out)
    md = format_markdown_table(summary)
    md_path = Path(args.md_out) if args.md_out else out.with_suffix(".md")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md + "\n", encoding="utf-8")
    s = summary.get("summary") or {}
    meta = summary.get("meta") or {}
    print(
        f"wrote {out}  pass@1={s.get('pass_at_1', 0):.3f} "
        f"n={s.get('n_episodes')} model={meta.get('model')}"
    )
    print(f"wrote {md_path}")
    if not args.quiet:
        print()
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
