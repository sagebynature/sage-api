from __future__ import annotations

from pathlib import Path

from sage import Agent
from sage.config import AgentConfig, load_config

from sage_api.models.schemas import AgentInfo


class AgentRegistry:
    def __init__(self, agents_dir: str) -> None:
        self._agents_dir = Path(agents_dir)
        self._templates: dict[str, AgentConfig] = {}

    def scan(self) -> dict[str, AgentConfig]:
        templates: dict[str, AgentConfig] = {}

        for config_path in self._agents_dir.rglob("AGENTS.md"):
            config = load_config(config_path)
            if config.name in templates:
                raise ValueError(f"Duplicate agent name '{config.name}' found in registry scan: {config_path}")
            templates[config.name] = config

        self._templates = templates
        return self._templates

    def get_template(self, agent_name: str) -> AgentConfig | None:
        return self._templates.get(agent_name)

    def list_agents(self) -> list[AgentInfo]:
        return [
            AgentInfo(name=config.name, description=config.description, capabilities=[])
            for config in sorted(self._templates.values(), key=lambda cfg: cfg.name)
        ]

    def create_instance(self, agent_name: str) -> Agent:
        config = self._templates.get(agent_name)
        if config is None:
            raise ValueError(f"Agent '{agent_name}' not found in registry")

        return Agent(
            name=config.name,
            model=config.model,
            description=config.description,
            body=config._body,
            tools=config.tools or [],
            memory=None,
            max_turns=config.max_turns,
            model_params=config.model_params.to_kwargs() or None,
        )

    def reload(self) -> None:
        templates: dict[str, AgentConfig] = {}

        for config_path in self._agents_dir.rglob("AGENTS.md"):
            config = load_config(config_path)
            if config.name in templates:
                raise ValueError(f"Duplicate agent name '{config.name}' found in registry scan: {config_path}")
            templates[config.name] = config

        self._templates = templates
