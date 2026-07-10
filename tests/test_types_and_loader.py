from cascade_env.tasks.loader import TaskLoader, episode_seed
from cascade_env.types import Action, ToolResult


def test_tool_result_truncate():
    big = "x" * 100_000
    tr = ToolResult.success("files.read", stdout=big)
    assert tr.truncated
    assert len(tr.stdout) < 100_000


def test_load_community_pack():
    loader = TaskLoader()
    packs = loader.list_packs()
    assert "community" in packs
    tasks = loader.list_tasks("community")
    assert len(tasks) >= 8
    t = loader.load_task("community", "community.T2.pagination_off_by_one.v1")
    assert t.family == "bugfix"
    assert t.mutations


def test_episode_seed_stable():
    a = episode_seed("community", "t", 42)
    b = episode_seed("community", "t", 42)
    c = episode_seed("community", "t", 43)
    assert a == b
    assert a != c


def test_action_parse():
    a = Action.model_validate({"tool": "files.read", "args": {"path": "x"}})
    assert a.tool == "files.read"
