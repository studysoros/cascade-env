#!/usr/bin/env python3
"""
Eval harness: N seeds × task set → JSON pass-rate summary (+ optional markdown).

Examples:
  # Scripted control baseline (no API key)
  uv run python scripts/eval_baselines.py --agent scripted --seeds 0,1,2

  # Frontier model (requires API key)
  uv run python scripts/eval_baselines.py --agent llm --provider xai --model grok-3 \\
    --seeds 0 --out docs/artifacts/baseline-grok-3-t1-t5.json

  # Subset
  uv run python scripts/eval_baselines.py --agent scripted \\
    --tasks community.T2.pagination_off_by_one.v1,community.T3.worker_disabled_config.v1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cascade_env.agents.eval import (
    DEFAULT_BASELINE_TASKS,
    EvalConfig,
    format_markdown_table,
    run_eval,
    write_summary,
)
from cascade_env.agents.llm_client import LLMError


def _parse_int_list(raw: str) -> list[int]:
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    return [int(p) for p in parts]


def _parse_task_list(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return list(DEFAULT_BASELINE_TASKS)
    return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cascade baseline eval harness")
    p.add_argument("--agent", choices=["scripted", "llm"], default="scripted")
    p.add_argument("--pack", default="community")
    p.add_argument("--runtime", default="local", choices=["local", "compose"])
    p.add_argument("--max-steps", type=int, default=40)
    p.add_argument(
        "--tasks",
        default=None,
        help="Comma-separated task ids (default: community T1–T5)",
    )
    p.add_argument("--seeds", default="0", help="Comma-separated seeds (default: 0)")
    p.add_argument("--provider", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--api-key", default=None)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument(
        "--out",
        default="docs/artifacts/baseline-summary.json",
        help="JSON summary output path",
    )
    p.add_argument(
        "--md-out",
        default=None,
        help="Optional markdown table path (default: alongside --out as .md)",
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    cfg = EvalConfig(
        tasks=_parse_task_list(args.tasks),
        seeds=_parse_int_list(args.seeds),
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
    except Exception as exc:  # noqa: BLE001
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    out = write_summary(summary, args.out)
    md = format_markdown_table(summary)
    md_path = Path(args.md_out) if args.md_out else out.with_suffix(".md")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md + "\n", encoding="utf-8")

    s = summary.get("summary") or {}
    meta = summary.get("meta") or {}
    print(
        f"wrote {out}  pass@1={s.get('pass_at_1', 0):.3f} "
        f"n={s.get('n_episodes')} model={meta.get('model')} "
        f"avg_steps={s.get('avg_steps', 0):.1f}"
    )
    print(f"wrote {md_path}")
    if not args.quiet:
        print()
        print(md)
    # exit 0 even if pass rate is 0 — harness success is independent of agent skill
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
