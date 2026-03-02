# Enhanced /v1/agents Endpoint

## Problem

The `GET /v1/agents` and `GET /v1/agents/{name}` endpoints return minimal
`AgentInfo` (name, description, always-empty capabilities list).  The registry
already loads rich config data — model, model_params, permissions, skills,
subagents, context — but none of it is exposed through the API.

## Consumer

Both frontend/dashboard UIs and external integrations (A2A protocol, other
services) need comprehensive agent metadata for display and programmatic
discovery.

## Approach: Two-tier response models

Separate summary and detail schemas following standard REST conventions.

- `GET /v1/agents` → `list[AgentSummary]` (compact)
- `GET /v1/agents/{name}` → `AgentDetail` (comprehensive)

System prompts (markdown body) are never exposed.  Skill content is excluded —
only metadata (name, description) is returned.

## Schema Design

### Reused from sage-agent SDK (no duplication)

- `sage.config.ModelParams` — temperature, max_tokens, top_p, top_k, etc.
- `sage.config.Permission` — read, edit, shell, web, memory, task, git
- `sage.config.ContextConfig` — compaction_threshold, reserve_tokens, etc.

### New in sage-api

```python
class SkillInfo(BaseModel):
    name: str
    description: str | None = None

class SubagentDetail(BaseModel):
    name: str
    description: str | None = None
    model: str
    max_turns: int
    skills: list[str]
    model_params: ModelParams
    permission: Permission | None

class AgentSummary(BaseModel):
    name: str
    description: str | None = None
    model: str
    skills_count: int
    subagents_count: int

class AgentDetail(BaseModel):
    name: str
    description: str | None = None
    model: str
    max_turns: int
    max_depth: int
    model_params: ModelParams
    permission: Permission | None
    skills: list[SkillInfo]
    subagents: list[SubagentDetail]
    context: ContextConfig | None
```

### Dropped

`AgentInfo` with its never-populated `capabilities` field is replaced by
`AgentSummary`.

## Registry Layer

- `list_agents()` returns `list[AgentSummary]` (populated from existing
  `_AgentInstance.config`)
- New `get_agent_detail(name)` returns `AgentDetail | None`, built from the
  private `_AgentInstance` (config + global_skills).  Keeps `_AgentInstance`
  encapsulated.
- `get_template()` remains for `create_instance()` usage.

## Router Layer

- `GET /v1/agents` calls `registry.list_agents()`, returns result directly.
- `GET /v1/agents/{name}` calls `registry.get_agent_detail(name)`, returns
  result or 404.
- Conversion logic lives inside the registry (factory methods), keeping the
  router thin.

## Testing

### Updated tests

- `test_api_agents.py` — assertions updated for `AgentSummary` / `AgentDetail`
- `test_agent_registry.py` — `list_agents` assertions updated for new fields

### New tests

- `test_get_agent_detail_returns_full_detail` — model, model_params, subagents,
  skills, permissions, context
- `test_get_agent_detail_returns_none_for_unknown`
- `test_list_agents_includes_model_and_counts`
- `test_get_agent_returns_subagents_with_detail` (API layer)
- `test_get_agent_returns_skills_with_metadata` (API layer)
- `test_get_agent_returns_model_params` (API layer)

### Test helpers

Extend `_create_instance()` to optionally create subagent `.md` files and skill
`SKILL.md` files.

## Future

- Add `version` field to `SkillInfo` once `sage.skills.loader.Skill` gains a
  `version` attribute.
