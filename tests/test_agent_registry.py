from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sage import Agent
from sage.config import AgentConfig, ModelParams

from sage_api.models.schemas import AgentDetail, AgentSummary
from sage_api.services.agent_registry import AgentRegistry


def _create_instance(
    root: Path,
    dir_name: str,
    *,
    primary_name: str = "main",
    model: str = "gpt-4o-mini",
    description: str = "A test agent",
    max_turns: int = 10,
    body: str = "You are a test assistant.",
    include_skills_dir: bool = False,
) -> Path:
    """Create a self-contained sage-agent instance directory."""
    instance_dir = root / dir_name
    agents_dir = instance_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Always set an explicit absolute skills_dir to prevent resolve_skills_dir
    # from falling back to global dirs like ~/.agents/skills or ~/.claude/skills.
    if include_skills_dir:
        skills_abs = instance_dir / "skills"
    else:
        skills_abs = instance_dir / "_empty_skills"
    skills_abs.mkdir(parents=True, exist_ok=True)
    skills_line = f'\nskills_dir = "{skills_abs}"'
    config_toml = f'agents_dir = "agents"\nprimary = "{primary_name}"{skills_line}\n'
    (instance_dir / "config.toml").write_text(config_toml, encoding="utf-8")

    agent_md = (
        f"---\nname: {primary_name}\nmodel: {model}\n"
        f"description: {description}\nmax_turns: {max_turns}\n---\n{body}\n"
    )
    (agents_dir / f"{primary_name}.md").write_text(agent_md, encoding="utf-8")

    return instance_dir


def _add_subagent(
    instance_dir: Path,
    name: str,
    *,
    model: str = "gpt-4o-mini",
    description: str = "A subagent",
    max_turns: int = 5,
    skills: list[str] | None = None,
    body: str = "You are a subagent.",
) -> None:
    """Add a subagent .md file to an existing instance."""
    agents_dir = instance_dir / "agents"
    skills_yaml = ""
    if skills:
        items = "\n".join(f"  - {s}" for s in skills)
        skills_yaml = f"skills:\n{items}\n"
    md = (
        f"---\nname: {name}\nmodel: {model}\n"
        f"description: {description}\nmax_turns: {max_turns}\n"
        f"{skills_yaml}---\n{body}\n"
    )
    (agents_dir / f"{name}.md").write_text(md, encoding="utf-8")


def _add_skill(instance_dir: Path, name: str, description: str = "A skill") -> None:
    """Add a skill SKILL.md to an existing instance."""
    skills_dir = instance_dir / "skills" / name
    skills_dir.mkdir(parents=True, exist_ok=True)
    md = f"---\nname: {name}\ndescription: \"{description}\"\n---\nSkill content.\n"
    (skills_dir / "SKILL.md").write_text(md, encoding="utf-8")


def test_scan_finds_agent_instances(tmp_path: Path) -> None:
    _create_instance(tmp_path, "alpha")
    _create_instance(tmp_path, "beta")

    registry = AgentRegistry(str(tmp_path))
    templates = registry.scan()

    assert set(templates.keys()) == {"alpha", "beta"}


def test_get_template_returns_agent_config(tmp_path: Path) -> None:
    _create_instance(tmp_path, "alpha", primary_name="orchestrator")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    template = registry.get_template("alpha")

    assert isinstance(template, AgentConfig)
    assert template is not None
    assert template.name == "orchestrator"


def test_get_template_returns_none_for_unknown_agent(tmp_path: Path) -> None:
    _create_instance(tmp_path, "alpha")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    assert registry.get_template("unknown") is None


def test_list_agents_returns_agent_info_models(tmp_path: Path) -> None:
    _create_instance(tmp_path, "zeta", description="Zeta agent")
    _create_instance(tmp_path, "alpha", description="Alpha agent")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    agents = registry.list_agents()

    assert all(isinstance(item, AgentSummary) for item in agents)
    assert [item.name for item in agents] == ["alpha", "zeta"]


def test_create_instance_returns_agent_with_memory_disabled(tmp_path: Path) -> None:
    _create_instance(tmp_path, "alpha")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    agent = registry.create_instance("alpha")

    assert isinstance(agent, Agent)
    assert agent.memory is None


def test_create_instance_raises_for_unknown_agent(tmp_path: Path) -> None:
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    with pytest.raises(ValueError, match="not found in registry"):
        registry.create_instance("missing")


def test_scan_skips_dirs_without_config_toml(tmp_path: Path) -> None:
    (tmp_path / "empty_dir").mkdir()
    _create_instance(tmp_path, "valid")

    registry = AgentRegistry(str(tmp_path))
    templates = registry.scan()

    assert set(templates.keys()) == {"valid"}


def test_reload_replaces_templates_with_filesystem_changes(tmp_path: Path) -> None:
    _create_instance(tmp_path, "alpha")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    assert registry.get_template("alpha") is not None

    shutil.rmtree(tmp_path / "alpha")
    _create_instance(tmp_path, "beta")

    registry.reload()

    assert registry.get_template("alpha") is None
    assert registry.get_template("beta") is not None


def test_list_agents_returns_summary_with_model_and_counts(tmp_path: Path) -> None:
    inst = _create_instance(tmp_path, "alpha", model="gpt-4o")
    _add_subagent(inst, "helper")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    agents = registry.list_agents()

    assert len(agents) == 1
    assert isinstance(agents[0], AgentSummary)
    assert agents[0].name == "alpha"
    assert agents[0].model == "gpt-4o"
    assert agents[0].subagents_count == 1
    assert agents[0].skills_count == 0


def test_get_agent_detail_returns_full_detail(tmp_path: Path) -> None:
    inst = _create_instance(
        tmp_path, "alpha", model="gpt-4o", max_turns=20, include_skills_dir=True,
    )
    _add_subagent(inst, "explorer", model="gpt-4o-mini", max_turns=5, skills=["clean-code"])
    _add_skill(inst, "clean-code", description="Code quality")

    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    detail = registry.get_agent_detail("alpha")

    assert isinstance(detail, AgentDetail)
    assert detail.name == "alpha"
    assert detail.model == "gpt-4o"
    assert detail.max_turns == 20
    assert isinstance(detail.model_params, ModelParams)
    assert len(detail.subagents) == 1
    assert detail.subagents[0].name == "explorer"
    assert detail.subagents[0].model == "gpt-4o-mini"
    assert detail.subagents[0].skills == ["clean-code"]
    assert len(detail.skills) == 1
    assert detail.skills[0].name == "clean-code"
    assert detail.skills[0].description == "Code quality"


def test_get_agent_detail_returns_none_for_unknown(tmp_path: Path) -> None:
    _create_instance(tmp_path, "alpha")
    registry = AgentRegistry(str(tmp_path))
    registry.scan()

    assert registry.get_agent_detail("missing") is None
