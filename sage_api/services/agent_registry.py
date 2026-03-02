from __future__ import annotations

import logging
from pathlib import Path

from sage import Agent
from sage.config import AgentConfig, load_config
from sage.main_config import MainConfig, load_main_config, resolve_and_apply_env
from sage.skills.loader import load_skills_from_directory, resolve_skills_dir

from sage_api.models.schemas import AgentDetail, AgentSummary, SkillInfo, SubagentDetail

logger = logging.getLogger(__name__)


class _AgentInstance:
    """Metadata for a discovered agent instance."""

    __slots__ = ("config", "base_dir", "central", "global_skills")

    def __init__(
        self,
        config: AgentConfig,
        base_dir: Path,
        central: MainConfig | None,
        global_skills: list,
    ) -> None:
        self.config = config
        self.base_dir = base_dir
        self.central = central
        self.global_skills = global_skills


class AgentRegistry:
    """Discovers self-contained sage-agent instances under agents_dir.

    Each subdirectory is expected to be a complete sage-agent project with its
    own ``config.toml``, ``agents/``, and optionally ``skills/``.  The primary
    agent declared in each ``config.toml`` is exposed as an API-level agent.
    """

    def __init__(self, agents_dir: str) -> None:
        self._agents_dir = Path(agents_dir)
        self._instances: dict[str, _AgentInstance] = {}

    def _discover_instance(self, instance_dir: Path) -> _AgentInstance | None:
        """Load a single sage-agent instance from *instance_dir*."""
        config_toml = instance_dir / "config.toml"
        if not config_toml.exists():
            logger.warning("Skipping %s — no config.toml found", instance_dir)
            return None

        central = load_main_config(config_toml)
        resolve_and_apply_env(central)

        agents_subdir = instance_dir / (central.agents_dir if central else "agents")
        if not agents_subdir.is_dir():
            logger.warning("Skipping %s — agents dir %s not found", instance_dir, agents_subdir)
            return None

        primary_name = central.primary if central else None
        if not primary_name:
            logger.warning("Skipping %s — no primary agent defined in config.toml", instance_dir)
            return None

        # Resolve skills
        skills_dir = resolve_skills_dir(central.skills_dir if central else None)
        global_skills = load_skills_from_directory(skills_dir) if skills_dir else []

        # Load the primary agent config (with central merge)
        primary_path = agents_subdir / f"{primary_name}.md"
        if not primary_path.exists():
            # Fall back to AGENTS.md in a subdirectory
            primary_path = agents_subdir / primary_name / "AGENTS.md"
        if not primary_path.exists():
            logger.warning("Skipping %s — primary agent file not found for '%s'", instance_dir, primary_name)
            return None

        config = load_config(primary_path, central=central)
        return _AgentInstance(
            config=config,
            base_dir=agents_subdir,
            central=central,
            global_skills=global_skills,
        )

    def scan(self) -> dict[str, AgentConfig]:
        instances: dict[str, _AgentInstance] = {}

        for child in sorted(self._agents_dir.iterdir()):
            if not child.is_dir():
                continue
            instance = self._discover_instance(child)
            if instance is None:
                continue
            name = child.name  # directory name is the API-level agent name
            if name in instances:
                raise ValueError(f"Duplicate agent name '{name}' in registry scan")
            instances[name] = instance

        self._instances = instances
        logger.info("Registry loaded %d agent(s): %s", len(instances), list(instances.keys()))
        return {name: inst.config for name, inst in self._instances.items()}

    def get_template(self, agent_name: str) -> AgentConfig | None:
        inst = self._instances.get(agent_name)
        return inst.config if inst else None

    def list_agents(self) -> list[AgentSummary]:
        return [
            AgentSummary(
                name=name,
                description=inst.config.description or None,
                model=inst.config.model,
                skills_count=len(inst.global_skills),
                subagents_count=len(inst.config.subagents),
            )
            for name, inst in sorted(self._instances.items())
        ]

    def get_agent_detail(self, agent_name: str) -> AgentDetail | None:
        inst = self._instances.get(agent_name)
        if inst is None:
            return None

        config = inst.config

        skills = [
            SkillInfo(name=s.name, description=s.description or None)
            for s in inst.global_skills
        ]

        subagents = [
            SubagentDetail(
                name=sa.name,
                description=sa.description or None,
                model=sa.model,
                max_turns=sa.max_turns,
                skills=sa.skills or [],
                model_params=sa.model_params,
                permission=sa.permission,
            )
            for sa in config.subagents
        ]

        return AgentDetail(
            name=agent_name,
            description=config.description or None,
            model=config.model,
            max_turns=config.max_turns,
            max_depth=config.max_depth,
            model_params=config.model_params,
            permission=config.permission,
            skills=skills,
            subagents=subagents,
            context=config.context,
        )

    def create_instance(self, agent_name: str) -> Agent:
        inst = self._instances.get(agent_name)
        if inst is None:
            raise ValueError(f"Agent '{agent_name}' not found in registry")

        # Disable memory for API deployments — session state is managed via Redis.
        api_config = inst.config.model_copy(update={"memory": None})

        return Agent._from_agent_config(api_config, inst.base_dir, global_skills=inst.global_skills)

    def reload(self) -> None:
        self.scan()
