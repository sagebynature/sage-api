from __future__ import annotations

from pathlib import Path

import pytest

from sage import Agent
from sage.config import AgentConfig

from sage_api.models.schemas import AgentInfo
from sage_api.services.agent_registry import AgentRegistry


def write_agent_file(
    path: Path,
    *,
    name: str,
    model: str = "gpt-4o-mini",
    description: str = "A test agent",
    max_turns: int = 10,
    body: str = "You are a test assistant.",
) -> None:
    content = f"---\nname: {name}\nmodel: {model}\ndescription: {description}\nmax_turns: {max_turns}\n---\n{body}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scan_finds_agents_recursively(tmp_path: Path) -> None:
    write_agent_file(tmp_path / "assistant" / "AGENTS.md", name="assistant")
    write_agent_file(tmp_path / "team" / "helper" / "AGENTS.md", name="helper")

    registry = AgentRegistry(str(tmp_path))
    templates = registry.scan()

    assert set(templates.keys()) == {"assistant", "helper"}


def test_get_template_returns_agent_config(tmp_path: Path) -> None:
    write_agent_file(tmp_path / "assistant" / "AGENTS.md", name="assistant")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    template = registry.get_template("assistant")

    assert isinstance(template, AgentConfig)
    assert template is not None
    assert template.name == "assistant"


def test_get_template_returns_none_for_unknown_agent(tmp_path: Path) -> None:
    write_agent_file(tmp_path / "assistant" / "AGENTS.md", name="assistant")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    assert registry.get_template("unknown") is None


def test_list_agents_returns_agent_info_models(tmp_path: Path) -> None:
    write_agent_file(tmp_path / "zeta" / "AGENTS.md", name="zeta", description="Zeta agent")
    write_agent_file(tmp_path / "alpha" / "AGENTS.md", name="alpha", description="Alpha agent")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    agents = registry.list_agents()

    assert all(isinstance(item, AgentInfo) for item in agents)
    assert [item.name for item in agents] == ["alpha", "zeta"]
    assert [item.capabilities for item in agents] == [[], []]


def test_create_instance_returns_agent_with_memory_disabled(tmp_path: Path) -> None:
    write_agent_file(tmp_path / "assistant" / "AGENTS.md", name="assistant")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    agent = registry.create_instance("assistant")

    assert isinstance(agent, Agent)
    assert agent.memory is None
    assert getattr(agent, "_memory", None) is None


def test_create_instance_raises_for_unknown_agent(tmp_path: Path) -> None:
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    with pytest.raises(ValueError, match="not found in registry"):
        registry.create_instance("missing")


def test_scan_raises_on_duplicate_agent_names(tmp_path: Path) -> None:
    write_agent_file(tmp_path / "one" / "AGENTS.md", name="duplicate")
    write_agent_file(tmp_path / "two" / "AGENTS.md", name="duplicate")
    registry = AgentRegistry(str(tmp_path))

    with pytest.raises(ValueError, match="Duplicate agent name 'duplicate'"):
        registry.scan()


def test_reload_replaces_templates_with_filesystem_changes(tmp_path: Path) -> None:
    write_agent_file(tmp_path / "assistant" / "AGENTS.md", name="assistant")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    old_template = registry.get_template("assistant")
    assert old_template is not None

    (tmp_path / "assistant" / "AGENTS.md").unlink()
    write_agent_file(tmp_path / "new" / "AGENTS.md", name="new-agent")

    registry.reload()

    assert registry.get_template("assistant") is None
    new_template = registry.get_template("new-agent")
    assert new_template is not None
    assert new_template.name == "new-agent"
