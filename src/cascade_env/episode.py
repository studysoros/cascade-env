"""Episode manager: materialize workspace, provision, inject, agent loop support."""

from __future__ import annotations

import atexit
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from cascade_env.config import CascadeConfig, get_config
from cascade_env.reward import step_reward, terminal_reward
from cascade_env.runtime import get_runtime
from cascade_env.runtime.base import EpisodeHandle, RuntimeBackend
from cascade_env.tasks.loader import TaskLoader, episode_seed
from cascade_env.tasks.mutators import apply_mutations
from cascade_env.tasks.schemas import TaskSpec
from cascade_env.trajectory import TrajectoryLogger
from cascade_env.types import (
    Action,
    Budget,
    EpisodePhase,
    EpisodeResult,
    Observation,
    TaskBrief,
    ToolResult,
)
from cascade_env.verifiers.orchestrator import evaluate_success, run_verifiers
from cascade_env.version import __version__


class EpisodeManager:
    def __init__(self, config: CascadeConfig | None = None) -> None:
        self.config = config or get_config()
        self.runtime: RuntimeBackend = get_runtime(self.config.runtime)
        self.loader = TaskLoader(self.config)
        self.handle: EpisodeHandle | None = None
        self.task: TaskSpec | None = None
        self.phase = EpisodePhase.DONE
        self.step_count = 0
        self.step_cost_accrued = 0.0
        self.violation_accrued = 0.0
        self.started_at = 0.0
        self.max_steps = self.config.max_steps
        self.max_wall_time_s = self.config.max_wall_time_s
        self.traj: TrajectoryLogger | None = None
        self.events: list[dict[str, Any]] = []
        self.last_tool: ToolResult | None = None
        self.episode_id = ""
        self.user_seed = 0
        self.pack_id = self.config.pack
        self._closed = True
        atexit.register(self.close)

    def reset(
        self,
        *,
        pack: str | None = None,
        task_id: str | None = None,
        seed: int | None = None,
    ) -> tuple[Observation, dict[str, Any]]:
        self.close()
        self._closed = False
        self.pack_id = pack or self.config.pack
        self.user_seed = 0 if seed is None else int(seed)
        if task_id is None:
            task_id = self.loader.sample_task_id(self.pack_id, seed=self.user_seed)
        self.task = self.loader.load_task(self.pack_id, task_id)
        self.episode_id = f"ep_{uuid.uuid4().hex[:12]}"
        self.step_count = 0
        self.step_cost_accrued = 0.0
        self.violation_accrued = 0.0
        self.events = []
        self.last_tool = None
        self.max_steps = int(self.task.budgets.get("max_steps", self.config.max_steps))
        self.max_wall_time_s = float(
            self.task.budgets.get("max_wall_time_s", self.config.max_wall_time_s)
        )
        self.started_at = time.time()

        work = self.config.resolved_work_root() / self.episode_id
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)

        self.phase = EpisodePhase.PROVISIONING
        self._materialize_workspace(work)
        seed_key = episode_seed(self.pack_id, self.task.id, self.user_seed, __version__)
        self.events.append({"event": "materialized", "seed": seed_key})

        traj_path = work / "trajectory.jsonl"
        self.traj = TrajectoryLogger(traj_path)
        self.traj.write(
            {
                "type": "episode_start",
                "episode_id": self.episode_id,
                "pack": self.pack_id,
                "task_id": self.task.id,
                "seed": self.user_seed,
                "seed_key": seed_key,
                "runtime": self.runtime.name,
            }
        )

        self.handle = self.runtime.provision(self.episode_id, work)
        ok = self.runtime.wait_healthy(self.handle, timeout_s=self.config.provision_timeout_s)
        if not ok:
            self.phase = EpisodePhase.TEARDOWN
            self._dump_failure("provision_failed")
            self.close()
            raise RuntimeError(
                f"Failed to provision healthy stack for episode {self.episode_id}. "
                f"See logs under {work / '.cascade_logs'}"
            )

        self.phase = EpisodePhase.HEALTHY_BASELINE
        # inject mutations (files already mutated pre-start for code/config;
        # restart to ensure injected code is loaded if mutations applied before start)
        self.phase = EpisodePhase.TASK_INJECTED
        self.runtime.apply_pending_sql(self.handle)
        # Restart worker/api so any pre-start file mutations are loaded
        self.runtime.restart_services(self.handle, ["api", "worker"])
        if not self.runtime.wait_healthy(self.handle, timeout_s=30):
            self._dump_failure("post_inject_unhealthy")
            self.close()
            raise RuntimeError("Stack unhealthy after task injection")

        self.phase = EpisodePhase.AGENT_CONTROL
        obs = self._observation()
        info = {
            "episode_id": self.episode_id,
            "task_id": self.task.id,
            "obs": obs.model_dump(mode="json"),
            "trajectory_path": str(traj_path),
        }
        return obs, info

    def step(self, action: Action | dict[str, Any]) -> tuple[Observation, float, bool, bool, dict]:
        if self._closed or self.handle is None or self.task is None:
            raise RuntimeError("Episode not active; call reset() first")
        if isinstance(action, dict):
            action = Action.model_validate(action)

        terminated = False
        truncated = False
        reward = 0.0
        info: dict[str, Any] = {"episode_id": self.episode_id}

        # budget checks
        if self.step_count >= self.max_steps:
            truncated = True
        elif time.time() - self.started_at >= self.max_wall_time_s:
            truncated = True

        if truncated:
            result = self._verify_and_score(truncated=True)
            obs = self._observation()
            info.update(result.model_dump(mode="json"))
            info["obs"] = obs.model_dump(mode="json")
            self.close()
            return obs, result.terminal_reward, False, True, info

        if not self._tool_allowed(action.tool):
            tr = ToolResult.failure(
                action.tool,
                "POLICY",
                stderr=f"tool not allowed for this task: {action.tool}",
            )
            self.last_tool = tr
            self.violation_accrued += 0.05
            reward = step_reward(self.config.step_cost, violation=0.05)
            self.step_cost_accrued += abs(reward)
            self.step_count += 1
            obs = self._observation()
            info["tool_result"] = tr.model_dump(mode="json")
            info["obs"] = obs.model_dump(mode="json")
            return obs, reward, False, False, info

        if action.tool == "submit.done":
            result = self._verify_and_score(truncated=False)
            obs = self._observation()
            info.update(result.model_dump(mode="json"))
            info["obs"] = obs.model_dump(mode="json")
            self.close()
            return obs, result.terminal_reward, True, False, info

        tr = self.runtime.exec_tool(self.handle, action.tool, action.args)
        self.last_tool = tr
        reward = step_reward(self.config.step_cost)
        self.step_cost_accrued += abs(reward)
        self.step_count += 1

        if self.traj:
            self.traj.write(
                {
                    "type": "step",
                    "episode_id": self.episode_id,
                    "step": self.step_count,
                    "action": action.model_dump(mode="json"),
                    "messages_delta": [
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": f"c{self.step_count}",
                                    "function": {
                                        "name": action.tool,
                                        "arguments": action.args,
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": f"c{self.step_count}",
                            "content": tr.model_dump(mode="json"),
                        },
                    ],
                    "reward": reward,
                    "info": {"tool_latency_ms": tr.duration_ms},
                }
            )

        # post-step budget
        if self.step_count >= self.max_steps:
            result = self._verify_and_score(truncated=True)
            obs = self._observation()
            info.update(result.model_dump(mode="json"))
            info["tool_result"] = tr.model_dump(mode="json")
            info["obs"] = obs.model_dump(mode="json")
            self.close()
            return obs, result.terminal_reward, False, True, info

        obs = self._observation()
        info["tool_result"] = tr.model_dump(mode="json")
        info["obs"] = obs.model_dump(mode="json")
        return obs, reward, terminated, truncated, info

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.phase = EpisodePhase.TEARDOWN
        try:
            if self.handle is not None:
                self.runtime.teardown(self.handle)
        finally:
            self.handle = None
            if self.traj:
                self.traj.write({"type": "episode_end", "episode_id": self.episode_id})
                self.traj.close()
                self.traj = None
            self.phase = EpisodePhase.DONE

    def _materialize_workspace(self, work: Path) -> None:
        assert self.task is not None
        scenario = self.task.scenario
        src = self.config.scenarios_dir() / scenario / "workspace_template"
        if not src.is_dir():
            raise FileNotFoundError(f"Scenario template missing: {src}")
        shutil.copytree(src, work, dirs_exist_ok=True)
        # copy public tests into workspace
        tests_src = self.config.scenarios_dir() / scenario / "tests" / "public"
        if tests_src.is_dir():
            dest = work / "tests" / "public"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(tests_src, dest)
        events = apply_mutations(work, self.task.mutations)
        for e in events:
            self.events.append({"event": "mutation", "detail": e})

    def _tool_allowed(self, tool: str) -> bool:
        assert self.task is not None
        allow = self.task.tools.allow
        for pattern in allow:
            if pattern.endswith(".*"):
                if tool.startswith(pattern[:-2]):
                    return True
            elif tool == pattern:
                return True
        return tool == "submit.done"

    def _verify_and_score(self, *, truncated: bool) -> EpisodeResult:
        assert self.handle is not None and self.task is not None
        self.phase = EpisodePhase.VERIFYING
        api_key = (self.handle.workspace / "configs" / "api_key.txt").read_text(
            encoding="utf-8"
        ).strip()
        results = run_verifiers(self.runtime, self.handle, self.task, api_key=api_key)
        success, partial, detail = evaluate_success(results, self.task)
        term_r = terminal_reward(
            success=success,
            partial=partial,
            step_cost_accrued=self.step_cost_accrued,
            violation_accrued=self.violation_accrued,
        )
        traj_path = None
        if self.traj:
            traj_path = str(self.traj.path)
            self.traj.write(
                {
                    "type": "verify",
                    "episode_id": self.episode_id,
                    "success": success,
                    "terminal_reward": term_r,
                    "verifiers": [r.model_dump(mode="json") for r in results],
                    "detail": detail,
                    "truncated": truncated,
                }
            )
        return EpisodeResult(
            episode_id=self.episode_id,
            success=success,
            terminal_reward=term_r,
            step_cost_accrued=self.step_cost_accrued,
            verifiers=results,
            truncated=truncated,
            terminated=not truncated,
            trajectory_path=traj_path,
        )

    def _observation(self) -> Observation:
        assert self.task is not None
        remaining = max(0, self.max_steps - self.step_count)
        wall_left = max(0.0, self.max_wall_time_s - (time.time() - self.started_at))
        services = []
        if self.handle:
            services = self.runtime.service_status(self.handle)
        hints = self.task.brief.hints if self.config.show_hints else []
        return Observation(
            episode_id=self.episode_id,
            step=self.step_count,
            task=TaskBrief(
                id=self.task.id,
                family=self.task.family,
                tier=self.task.tier,
                title=self.task.brief.title,
                description=self.task.brief.description,
                public_success_criteria=self.task.brief.public_success_criteria,
                constraints=self.task.brief.constraints,
            ),
            budget=Budget(
                steps_remaining=remaining,
                max_steps=self.max_steps,
                wall_time_remaining_s=wall_left,
                max_wall_time_s=self.max_wall_time_s,
                step_cost=self.config.step_cost,
            ),
            services=services,
            hints=hints,
            last_tool_result=self.last_tool,
            recent_events=self.events[-10:],
            runtime=self.runtime.name,
            phase=self.phase.value,
        )

    def _dump_failure(self, reason: str) -> None:
        if not self.handle:
            return
        fail_dir = self.handle.workspace / "failure"
        fail_dir.mkdir(parents=True, exist_ok=True)
        (fail_dir / "reason.txt").write_text(reason, encoding="utf-8")
        if self.traj:
            self.traj.write({"type": "failure", "reason": reason})
