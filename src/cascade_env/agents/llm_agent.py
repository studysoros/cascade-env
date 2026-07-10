"""LLM tool-calling agent loop for Cascade-v0."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from cascade_env.agents.llm_client import LLMClient, ModelTurn, ToolCall, estimate_cost_usd
from cascade_env.agents.tools_schema import cascade_tool_name, system_prompt


@dataclass
class EpisodeOutcome:
    task_id: str
    success: bool
    steps: int
    terminal_reward: float
    total_step_reward: float
    truncated: bool
    terminated: bool
    verifiers: dict[str, bool] = field(default_factory=dict)
    trajectory_path: str | None = None
    episode_id: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    estimated_cost_usd: float | None = None
    model: str | None = None
    provider: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "steps": self.steps,
            "terminal_reward": self.terminal_reward,
            "total_step_reward": self.total_step_reward,
            "truncated": self.truncated,
            "terminated": self.terminated,
            "verifiers": self.verifiers,
            # Portable: avoid machine-local absolute paths in checked-in JSON
            "trajectory_path": _portable_traj_path(self.trajectory_path, self.episode_id),
            "episode_id": self.episode_id,
            "usage": self.usage,
            "estimated_cost_usd": self.estimated_cost_usd,
            "model": self.model,
            "provider": self.provider,
            "error": self.error,
        }


def _portable_traj_path(path: str | None, episode_id: str | None) -> str | None:
    if not path:
        return None
    if episode_id:
        return f"{episode_id}/trajectory.jsonl"
    # last two components if present
    parts = path.replace("\\", "/").rstrip("/").split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return parts[-1]


def build_initial_messages(obs: dict[str, Any]) -> list[dict[str, Any]]:
    """System + user messages from a Cascade observation dict."""
    task = obs.get("task") or {}
    budget = obs.get("budget") or {}
    criteria = task.get("public_success_criteria") or []
    constraints = task.get("constraints") or []
    services = obs.get("services") or []
    svc_line = ", ".join(
        f"{s.get('name')}={s.get('status')}" for s in services
    ) or "(unknown)"

    criteria_txt = "\n".join(f"- {c}" for c in criteria) or "- (see description)"
    constraints_txt = "\n".join(f"- {c}" for c in constraints) or "- none listed"

    user = f"""## Task
**ID:** {task.get('id')}
**Family / tier:** {task.get('family')} / {task.get('tier')}
**Title:** {task.get('title')}

### Description
{task.get('description')}

### Public success criteria
{criteria_txt}

### Constraints
{constraints_txt}

### Runtime
- runtime: {obs.get('runtime')}
- step: {obs.get('step')}
- steps_remaining: {budget.get('steps_remaining')}
- services: {svc_line}

Diagnose the fault and repair the sandbox. When done, call submit_done.
"""
    return [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user},
    ]


def tool_call_to_action(tc: ToolCall) -> dict[str, Any]:
    """Convert a model tool call into a Cascade action dict."""
    name = cascade_tool_name(tc.name)
    args = dict(tc.arguments or {})
    # normalize common aliases
    if name == "shell.exec" and "argv" not in args and "cmd" in args:
        args["argv"] = args.pop("cmd")
    if name == "http.request" and "method" not in args:
        args["method"] = "GET"
    return {"tool": name, "args": args}


def append_assistant_turn(messages: list[dict[str, Any]], turn: ModelTurn) -> None:
    """Append OpenAI-style assistant message (with tool_calls if any)."""
    msg: dict[str, Any] = {
        "role": "assistant",
        "content": turn.content if turn.content is not None else None,
    }
    if turn.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in turn.tool_calls
        ]
    messages.append(msg)


def append_tool_result(
    messages: list[dict[str, Any]],
    *,
    tool_call_id: str,
    tool_name: str,
    result: dict[str, Any] | None,
    compact: bool = True,
) -> None:
    content = _format_tool_result(result, compact=compact)
    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": content,
        }
    )


def run_llm_episode(
    env: Any,
    client: LLMClient,
    *,
    seed: int = 0,
    task_id: str | None = None,
    verbose: bool = False,
    log: Callable[[str], None] | None = None,
    max_model_turns: int | None = None,
) -> EpisodeOutcome:
    """
    Run one Cascade episode driven by ``client``.

    ``env`` must support reset/step/close with Cascade-v0 semantics
    (JSON observation string + action dict).
    """
    _log = log or (print if verbose else (lambda _m: None))

    options: dict[str, Any] = {}
    if task_id:
        options["task_id"] = task_id
    obs_s, info = env.reset(seed=seed, options=options or None)
    obs = json.loads(obs_s) if isinstance(obs_s, str) else obs_s
    resolved_task = (obs.get("task") or {}).get("id") or task_id or "unknown"

    messages = build_initial_messages(obs)
    terminated = truncated = False
    total_r = 0.0
    steps = 0
    model_turns = 0
    last_info = info

    try:
        while not (terminated or truncated):
            if max_model_turns is not None and model_turns >= max_model_turns:
                # force submit to close cleanly if model loops
                action = {"tool": "submit.done", "args": {}}
                obs_s, reward, terminated, truncated, last_info = env.step(action)
                total_r += float(reward)
                steps += 1
                break

            turn = client.complete(messages)
            model_turns += 1
            append_assistant_turn(messages, turn)

            if not turn.tool_calls:
                # Model replied with text only — nudge once, then submit.
                _log(f"model text-only turn: {(turn.content or '')[:200]}")
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You must call a tool. Continue diagnosis or call "
                            "submit_done if finished."
                        ),
                    }
                )
                # second chance
                turn = client.complete(messages)
                model_turns += 1
                append_assistant_turn(messages, turn)
                if not turn.tool_calls:
                    action = {"tool": "submit.done", "args": {}}
                    obs_s, reward, terminated, truncated, last_info = env.step(action)
                    total_r += float(reward)
                    steps += 1
                    break

            for tc in turn.tool_calls:
                action = tool_call_to_action(tc)
                _log(f"step~{steps} tool={action['tool']} args_keys={list(action['args'])}")
                obs_s, reward, terminated, truncated, last_info = env.step(action)
                total_r += float(reward)
                steps += 1
                tr = last_info.get("tool_result")
                # After submit.done, tool_result may be absent; use verifiers summary
                if action["tool"] == "submit.done" or tr is None:
                    tr = {
                        "ok": bool(last_info.get("success")),
                        "tool": action["tool"],
                        "data": {
                            "success": last_info.get("success"),
                            "verifiers": {
                                v["id"]: v["passed"]
                                for v in (last_info.get("verifiers") or [])
                            },
                        },
                    }
                append_tool_result(
                    messages,
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    result=tr if isinstance(tr, dict) else {"raw": tr},
                )
                if terminated or truncated:
                    break

            if isinstance(obs_s, str):
                try:
                    obs = json.loads(obs_s)
                except json.JSONDecodeError:
                    pass

        usage = client.usage.as_dict()
        cost = estimate_cost_usd(
            client.model,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )
        return EpisodeOutcome(
            task_id=resolved_task,
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
            usage=usage,
            estimated_cost_usd=cost,
            model=client.model,
            provider=client.provider,
        )
    except Exception as exc:  # noqa: BLE001 — surface as episode failure
        usage = client.usage.as_dict()
        return EpisodeOutcome(
            task_id=resolved_task,
            success=False,
            steps=steps,
            terminal_reward=0.0,
            total_step_reward=total_r,
            truncated=True,
            terminated=False,
            trajectory_path=last_info.get("trajectory_path") if last_info else None,
            episode_id=last_info.get("episode_id") if last_info else None,
            usage=usage,
            model=client.model,
            provider=client.provider,
            error=f"{type(exc).__name__}: {exc}",
        )


def _format_tool_result(result: dict[str, Any] | None, *, compact: bool) -> str:
    if result is None:
        return json.dumps({"ok": False, "error": "no tool_result"})
    if not compact:
        return json.dumps(result, ensure_ascii=False, default=str)
    # Keep token budget under control for long stdout
    data = dict(result)
    for key in ("stdout", "stderr"):
        val = data.get(key)
        if isinstance(val, str) and len(val) > 6000:
            data[key] = val[:6000] + "\n...[truncated for LLM context]"
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) > 12_000:
        text = text[:12_000] + "...[truncated]"
    return text
