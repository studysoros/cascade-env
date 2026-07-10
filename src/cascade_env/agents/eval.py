"""Batch eval harness: N seeds × task set → JSON pass-rate summary."""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import cascade_env
import gymnasium as gym

from cascade_env.agents.llm_agent import EpisodeOutcome, run_llm_episode
from cascade_env.agents.llm_client import LLMClient
from cascade_env.agents.scripted import scripted_policy
from cascade_env.version import __version__

AgentKind = Literal["scripted", "llm"]

# Default public baseline card (L1–L2)
DEFAULT_BASELINE_TASKS: tuple[str, ...] = (
    "community.T1.worker_retry_storm.v1",
    "community.T2.pagination_off_by_one.v1",
    "community.T3.worker_disabled_config.v1",
    "community.T4.bad_product_prices.v1",
    "community.T5.discount_field.v1",
)


@dataclass
class EvalConfig:
    tasks: list[str] = field(default_factory=lambda: list(DEFAULT_BASELINE_TASKS))
    seeds: list[int] = field(default_factory=lambda: [0])
    pack: str = "community"
    runtime: str = "local"
    max_steps: int = 40
    agent: AgentKind = "scripted"
    # LLM options
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    verbose: bool = False


def run_scripted_episode(
    env: Any,
    *,
    seed: int = 0,
    task_id: str | None = None,
) -> EpisodeOutcome:
    options: dict[str, Any] = {}
    if task_id:
        options["task_id"] = task_id
    obs_s, info = env.reset(seed=seed, options=options or None)
    obs = json.loads(obs_s) if isinstance(obs_s, str) else obs_s
    resolved = (obs.get("task") or {}).get("id") or task_id or "unknown"
    terminated = truncated = False
    total_r = 0.0
    steps = 0
    last_info = info
    while not (terminated or truncated):
        action = scripted_policy(obs, last_info)
        obs_s, reward, terminated, truncated, last_info = env.step(action)
        total_r += float(reward)
        steps += 1
        obs = json.loads(obs_s) if isinstance(obs_s, str) else obs_s
    return EpisodeOutcome(
        task_id=resolved,
        success=bool(last_info.get("success")),
        steps=steps,
        terminal_reward=float(last_info.get("terminal_reward", total_r) or total_r),
        total_step_reward=total_r,
        truncated=bool(truncated),
        terminated=bool(terminated),
        verifiers={
            v["id"]: v["passed"] for v in (last_info.get("verifiers") or [])
        },
        trajectory_path=last_info.get("trajectory_path"),
        episode_id=last_info.get("episode_id"),
        model="scripted",
        provider="scripted",
    )


def run_eval(
    cfg: EvalConfig,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Run cfg.seeds × cfg.tasks episodes and return a JSON-serializable summary.

    For agent=llm a single LLMClient is reused across episodes (usage accumulated).
    """
    log = progress or (print if cfg.verbose else (lambda _m: None))
    cascade_env.register_envs()

    client: LLMClient | None = None
    if cfg.agent == "llm":
        client = LLMClient(
            provider=cfg.provider,
            model=cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            temperature=cfg.temperature,
        )
        client.require_api_key()

    started = time.time()
    date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    episodes: list[dict[str, Any]] = []
    by_task: dict[str, list[EpisodeOutcome]] = {t: [] for t in cfg.tasks}

    try:
        for task_id in cfg.tasks:
            for seed in cfg.seeds:
                log(f"eval task={task_id} seed={seed} agent={cfg.agent}")
                env = gym.make(
                    "Cascade-v0",
                    pack=cfg.pack,
                    runtime=cfg.runtime,
                    task_id=task_id,
                    max_steps=cfg.max_steps,
                )
                try:
                    if cfg.agent == "scripted":
                        outcome = run_scripted_episode(env, seed=seed, task_id=task_id)
                    else:
                        assert client is not None
                        # fresh usage view per episode: snapshot deltas
                        before = client.usage.as_dict()
                        outcome = run_llm_episode(
                            env,
                            client,
                            seed=seed,
                            task_id=task_id,
                            verbose=cfg.verbose,
                            log=log if cfg.verbose else None,
                        )
                        after = client.usage.as_dict()
                        outcome.usage = {
                            "prompt_tokens": after["prompt_tokens"] - before["prompt_tokens"],
                            "completion_tokens": after["completion_tokens"]
                            - before["completion_tokens"],
                            "total_tokens": after["total_tokens"] - before["total_tokens"],
                            "api_calls": after["api_calls"] - before["api_calls"],
                        }
                    by_task[task_id].append(outcome)
                    ep = outcome.as_dict()
                    ep["seed"] = seed
                    episodes.append(ep)
                    log(
                        f"  → success={outcome.success} steps={outcome.steps} "
                        f"R={outcome.terminal_reward:.4f}"
                        + (f" err={outcome.error}" if outcome.error else "")
                    )
                finally:
                    env.close()
    finally:
        if client is not None:
            client.close()

    task_rows: dict[str, Any] = {}
    for task_id, outs in by_task.items():
        n = len(outs)
        passes = sum(1 for o in outs if o.success)
        steps_list = [o.steps for o in outs]
        rewards = [o.terminal_reward for o in outs]
        task_rows[task_id] = {
            "n": n,
            "passes": passes,
            "pass_at_1": (passes / n) if n else 0.0,
            "avg_steps": statistics.mean(steps_list) if steps_list else 0.0,
            "avg_terminal_reward": statistics.mean(rewards) if rewards else 0.0,
            "episodes": [o.as_dict() for o in outs],
        }

    all_outs = [o for outs in by_task.values() for o in outs]
    n_all = len(all_outs)
    pass_all = sum(1 for o in all_outs if o.success)
    total_prompt = sum((o.usage or {}).get("prompt_tokens", 0) for o in all_outs)
    total_completion = sum((o.usage or {}).get("completion_tokens", 0) for o in all_outs)
    costs = [o.estimated_cost_usd for o in all_outs if o.estimated_cost_usd is not None]
    total_cost = sum(costs) if costs else None

    model_name = cfg.model
    provider_name = cfg.provider
    if cfg.agent == "scripted":
        model_name = "scripted"
        provider_name = "scripted"
    elif client is not None:
        model_name = client.model
        provider_name = client.provider

    summary = {
        "meta": {
            "date": date_iso,
            "agent": cfg.agent,
            "model": model_name,
            "provider": provider_name,
            "runtime": cfg.runtime,
            "pack": cfg.pack,
            "tasks": list(cfg.tasks),
            "seeds": list(cfg.seeds),
            "max_steps": cfg.max_steps,
            "cascade_version": __version__,
            "elapsed_s": round(time.time() - started, 2),
        },
        "tasks": task_rows,
        "summary": {
            "n_episodes": n_all,
            "passes": pass_all,
            "pass_at_1": (pass_all / n_all) if n_all else 0.0,
            "avg_steps": (
                statistics.mean([o.steps for o in all_outs]) if all_outs else 0.0
            ),
            "avg_terminal_reward": (
                statistics.mean([o.terminal_reward for o in all_outs]) if all_outs else 0.0
            ),
            "usage_total": {
                "prompt_tokens": total_prompt,
                "completion_tokens": total_completion,
                "total_tokens": total_prompt + total_completion,
            },
            "estimated_cost_usd_total": total_cost,
        },
        "episodes": episodes,
    }
    return summary


def write_summary(summary: dict[str, Any], path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def format_markdown_table(summary: dict[str, Any]) -> str:
    """Render a compact markdown pass-rate card from an eval summary."""
    meta = summary.get("meta") or {}
    tasks = summary.get("tasks") or {}
    s = summary.get("summary") or {}
    lines = [
        f"| Model | Date | Pack | pass@1 | Avg steps | Runtime | Est. cost |",
        f"|-------|------|------|--------|-----------|---------|-----------|",
        (
            f"| {meta.get('model')} | {meta.get('date')} | "
            f"{meta.get('pack')} T1–T5 | {s.get('pass_at_1', 0):.2f} | "
            f"{s.get('avg_steps', 0):.1f} | {meta.get('runtime')} | "
            f"{_fmt_cost(s.get('estimated_cost_usd_total'))} |"
        ),
        "",
        "### Per-task",
        "",
        "| Task ID | pass@1 | n | Avg steps | Avg R |",
        "|---------|--------|---|-----------|-------|",
    ]
    for tid, row in tasks.items():
        lines.append(
            f"| `{tid}` | {row.get('pass_at_1', 0):.2f} | {row.get('n')} | "
            f"{row.get('avg_steps', 0):.1f} | {row.get('avg_terminal_reward', 0):.3f} |"
        )
    return "\n".join(lines)


def _fmt_cost(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"${float(v):.4f}"
    except (TypeError, ValueError):
        return "—"
