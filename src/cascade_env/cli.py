"""cascade CLI: doctor | gc | list-tasks | run-episode."""

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
        choices=["scripted", "random", "manual"],
        help="scripted=known-fix agent for demos; random=noop; manual=stdin tools",
    )
    p_run.add_argument("--max-steps", type=int, default=40)

    args = parser.parse_args(argv)
    if args.cmd == "doctor":
        return cmd_doctor()
    if args.cmd == "gc":
        return cmd_gc(args.ttl_hours, args.dry_run)
    if args.cmd == "list-tasks":
        return cmd_list_tasks(args.pack)
    if args.cmd == "run-episode":
        return cmd_run_episode(args)
    return 1


def cmd_doctor() -> int:
    cfg = get_config()
    print(f"cascade {__version__}")
    print(f"python      {sys.version.split()[0]}")
    print(f"data_root   {cfg.resolved_data_root()}")
    print(f"work_root   {cfg.resolved_work_root()}")
    print(f"scenarios   {cfg.scenarios_dir()} exists={cfg.scenarios_dir().is_dir()}")
    print(f"packs       {cfg.packs_dir()} exists={cfg.packs_dir().is_dir()}")
    extra = cfg.extra_pack_dirs()
    if extra:
        for p in extra:
            print(f"extra_pack  {p} exists={p.is_dir()} pack_yaml={(p / 'pack.yaml').exists()}")
    else:
        print("extra_pack  (none — set CASCADE_EXTRA_PACKS or CASCADE_HOLDOUT_DIR for sealed packs)")

    docker_ok = shutil.which("docker") is not None
    print(f"docker_bin  {docker_ok}")
    if docker_ok:
        import subprocess

        try:
            r = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            print(f"docker_daemon {'ok' if r.returncode == 0 else 'not running'}")
        except Exception as exc:  # noqa: BLE001
            print(f"docker_daemon error: {exc}")

    # orphan workspaces
    root = cfg.resolved_work_root()
    orphans = list(root.glob("ep_*")) if root.is_dir() else []
    print(f"orphan_eps  {len(orphans)}")
    print("runtime_default local (set CASCADE_RUNTIME=compose for Docker)")
    print("SANDBOX ONLY — never attach tools to real production credentials.")
    return 0


def cmd_gc(ttl_hours: float, dry_run: bool) -> int:
    cfg = get_config()
    root = cfg.resolved_work_root()
    if not root.is_dir():
        print("nothing to gc")
        return 0
    cutoff = time.time() - ttl_hours * 3600
    removed = 0
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
    print(f"gc complete: {removed} episode dirs")
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


if __name__ == "__main__":
    raise SystemExit(main())
