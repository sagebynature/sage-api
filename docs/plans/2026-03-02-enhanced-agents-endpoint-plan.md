# Enhanced /v1/agents Endpoint — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the minimal `AgentInfo` response with `AgentSummary` (list) and `AgentDetail` (detail) endpoints that expose model, subagents, skills, permissions, and model params.

**Architecture:** Two-tier response models. `AgentSummary` for the list endpoint (compact), `AgentDetail` for the detail endpoint (comprehensive). Conversion logic lives in the registry service. SDK models (`ModelParams`, `Permission`, `ContextConfig`) are reused directly — no duplication.

**Tech Stack:** FastAPI, Pydantic, sage-agent SDK (`sage.config`, `sage.skills.loader`)

---

### Task 1: Add new schema models to schemas.py

**Files:**
- Modify: `sage_api/models/schemas.py:1-38`
- Test: `tests/test_models.py`

**Step 1: Write failing tests for new schema models**

Add to `tests/test_models.py`:

```python
from sage.config import ContextConfig, ModelParams, Permission

from sage_api.models.schemas import (
    AgentDetail,
    AgentSummary,
    SkillInfo,
    SubagentDetail,
)


class TestSkillInfo:
    def test_minimal(self):
        info = SkillInfo(name="clean-code")
        assert info.name == "clean-code"
        assert info.description is None

    def test_with_description(self):
        info = SkillInfo(name="clean-code", description="Code quality skill")
        assert info.description == "Code quality skill"


class TestSubagentDetail:
    def test_full_fields(self):
        detail = SubagentDetail(
            name="explorer",
            description="Explores code",
            model="gpt-4o",
            max_turns=10,
            skills=["clean-code"],
            model_params=ModelParams(temperature=0.0, max_tokens=4096),
            permission=Permission(read="allow", edit="deny"),
        )
        assert detail.name == "explorer"
        assert detail.model_params.temperature == 0.0
        assert detail.permission.read == "allow"
        assert detail.skills == ["clean-code"]

    def test_null_permission(self):
        detail = SubagentDetail(
            name="helper",
            model="gpt-4o-mini",
            max_turns=5,
            skills=[],
            model_params=ModelParams(),
            permission=None,
        )
        assert detail.permission is None


class TestAgentSummary:
    def test_full_fields(self):
        summary = AgentSummary(
            name="coder",
            description="A coding agent",
            model="claude-sonnet-4-6",
            skills_count=3,
            subagents_count=2,
        )
        assert summary.name == "coder"
        assert summary.model == "claude-sonnet-4-6"
        assert summary.skills_count == 3
        assert summary.subagents_count == 2

    def test_null_description(self):
        summary = AgentSummary(
            name="helper",
            model="gpt-4o",
            skills_count=0,
            subagents_count=0,
        )
        assert summary.description is None


class TestAgentDetail:
    def test_full_fields(self):
        detail = AgentDetail(
            name="coder",
            description="A coding agent",
            model="claude-sonnet-4-6",
            max_turns=25,
            max_depth=3,
            model_params=ModelParams(temperature=0.0, max_tokens=8192),
            permission=Permission(read="allow", edit="allow"),
            skills=[SkillInfo(name="clean-code", description="Code quality")],
            subagents=[
                SubagentDetail(
                    name="explorer",
                    description="Explores code",
                    model="gpt-4o",
                    max_turns=10,
                    skills=[],
                    model_params=ModelParams(),
                    permission=Permission(read="allow"),
                ),
            ],
            context=ContextConfig(compaction_threshold=0.75, reserve_tokens=4096),
        )
        assert detail.name == "coder"
        assert len(detail.subagents) == 1
        assert detail.subagents[0].name == "explorer"
        assert len(detail.skills) == 1
        assert detail.context.reserve_tokens == 4096

    def test_minimal(self):
        detail = AgentDetail(
            name="simple",
            model="gpt-4o-mini",
            max_turns=10,
            max_depth=3,
            model_params=ModelParams(),
            permission=None,
            skills=[],
            subagents=[],
            context=None,
        )
        assert detail.permission is None
        assert detail.context is None
        assert detail.subagents == []

    def test_json_round_trip(self):
        detail = AgentDetail(
            name="rt",
            model="gpt-4o",
            max_turns=10,
            max_depth=3,
            model_params=ModelParams(temperature=0.5),
            permission=Permission(read="allow"),
            skills=[SkillInfo(name="s1")],
            subagents=[],
            context=None,
        )
        json_str = detail.model_dump_json()
        restored = AgentDetail.model_validate_json(json_str)
        assert restored.name == "rt"
        assert restored.model_params.temperature == 0.5
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py -v -k "SkillInfo or SubagentDetail or AgentSummary or AgentDetail"`
Expected: FAIL — ImportError (classes don't exist yet)

**Step 3: Implement the new schema models**

In `sage_api/models/schemas.py`, add imports and new classes. Replace the
`AgentInfo` class (lines 30-37) with the four new models. Keep `AgentInfo`
as an alias for backward compatibility until all consumers are migrated:

```python
# Add to imports (line 8 area)
from sage.config import ContextConfig, ModelParams, Permission

# Replace AgentInfo (lines 30-37) with:

class SkillInfo(BaseModel):
    """Metadata for a skill (excludes content)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None = None


class SubagentDetail(BaseModel):
    """Full detail for a subagent."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None = None
    model: str
    max_turns: int
    skills: list[str]
    model_params: ModelParams
    permission: Permission | None = None


class AgentSummary(BaseModel):
    """Summary information about an agent (for list endpoints)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None = None
    model: str
    skills_count: int
    subagents_count: int


class AgentDetail(BaseModel):
    """Comprehensive agent detail (for detail endpoints)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None = None
    model: str
    max_turns: int
    max_depth: int
    model_params: ModelParams
    permission: Permission | None = None
    skills: list[SkillInfo]
    subagents: list[SubagentDetail]
    context: ContextConfig | None = None


# Keep AgentInfo as a backward-compat alias until Task 4 removes all usages
AgentInfo = AgentSummary
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v -k "SkillInfo or SubagentDetail or AgentSummary or AgentDetail"`
Expected: PASS

**Step 5: Commit**

```bash
git add sage_api/models/schemas.py tests/test_models.py
git commit -m "feat: add AgentSummary, AgentDetail, SkillInfo, SubagentDetail schemas"
```

---

### Task 2: Enhance AgentRegistry with list_agents and get_agent_detail

**Files:**
- Modify: `sage_api/services/agent_registry.py:109-113`
- Test: `tests/test_agent_registry.py`

**Step 1: Write failing tests**

Update existing test and add new tests in `tests/test_agent_registry.py`.
First, enhance the `_create_instance` helper to support subagents and skills:

```python
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
```

Update `_create_instance` to accept optional `skills_dir` in config.toml:

```python
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
    instance_dir = root / dir_name
    agents_dir = instance_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    skills_line = '\nskills_dir = "skills"' if include_skills_dir else ""
    config_toml = f'agents_dir = "agents"\nprimary = "{primary_name}"{skills_line}\n'
    (instance_dir / "config.toml").write_text(config_toml, encoding="utf-8")

    agent_md = (
        f"---\nname: {primary_name}\nmodel: {model}\n"
        f"description: {description}\nmax_turns: {max_turns}\n---\n{body}\n"
    )
    (agents_dir / f"{primary_name}.md").write_text(agent_md, encoding="utf-8")

    return instance_dir
```

Now add new tests:

```python
from sage.config import ModelParams

from sage_api.models.schemas import AgentDetail, AgentSummary


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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_registry.py -v -k "summary or detail"`
Expected: FAIL — `AgentSummary` import works (from Task 1), but `list_agents`
returns wrong type and `get_agent_detail` doesn't exist.

**Step 3: Implement registry changes**

In `sage_api/services/agent_registry.py`:

1. Update imports (line 11): replace `AgentInfo` with `AgentDetail, AgentSummary, SkillInfo, SubagentDetail`
2. Replace `list_agents()` method (lines 109-113)
3. Add `get_agent_detail()` method

```python
# Updated imports
from sage_api.models.schemas import AgentDetail, AgentSummary, SkillInfo, SubagentDetail

# Replace list_agents (lines 109-113)
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

# Add after list_agents
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
        context=inst.central.context if inst.central else None,
    )
```

Note: The `name` field in `AgentDetail` uses the directory name (`agent_name`
parameter) which is the API-level name, not `config.name` which is the primary
agent's internal name (e.g. "orchestrator"). This matches the current behavior
of `list_agents()`.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_registry.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add sage_api/services/agent_registry.py tests/test_agent_registry.py
git commit -m "feat: add get_agent_detail and enhance list_agents in registry"
```

---

### Task 3: Update the agents router

**Files:**
- Modify: `sage_api/api/agents.py:1-55`
- Test: `tests/test_api_agents.py`

**Step 1: Write failing tests**

Rewrite `tests/test_api_agents.py` to test the new response shapes.
The `TestListAgents` tests now assert `AgentSummary` fields. The `TestGetAgent`
tests now mock `get_agent_detail` instead of `get_template`:

```python
"""Tests for agent discovery REST endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sage.config import ModelParams, Permission

from sage_api.api.agents import router
from sage_api.config import get_settings
from sage_api.models.schemas import AgentDetail, AgentSummary, SkillInfo, SubagentDetail
from sage_api.services.agent_registry import AgentRegistry


@pytest.fixture()
def mock_registry() -> MagicMock:
    return MagicMock(spec=AgentRegistry)


@pytest.fixture()
def app(monkeypatch, mock_registry) -> FastAPI:
    monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
    get_settings.cache_clear()
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.registry = mock_registry
    return test_app


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


AUTH_HEADERS = {"X-API-Key": "test-key"}


class TestListAgents:

    def test_list_returns_empty_when_no_agents(self, client, mock_registry):
        mock_registry.list_agents.return_value = []
        response = client.get("/v1/agents", headers=AUTH_HEADERS)
        assert response.status_code == 200
        assert response.json() == []
        mock_registry.list_agents.assert_called_once()

    def test_list_returns_summary_fields(self, client, mock_registry):
        agents = [
            AgentSummary(
                name="alpha",
                description="Alpha agent",
                model="gpt-4o",
                skills_count=2,
                subagents_count=1,
            ),
            AgentSummary(
                name="beta",
                description=None,
                model="gpt-4o-mini",
                skills_count=0,
                subagents_count=0,
            ),
        ]
        mock_registry.list_agents.return_value = agents
        response = client.get("/v1/agents", headers=AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "alpha"
        assert data[0]["model"] == "gpt-4o"
        assert data[0]["skills_count"] == 2
        assert data[0]["subagents_count"] == 1
        assert data[1]["description"] is None

    def test_list_missing_auth_returns_401(self, client, mock_registry):
        response = client.get("/v1/agents")
        assert response.status_code == 401
        mock_registry.list_agents.assert_not_called()

    def test_list_wrong_auth_returns_401(self, client, mock_registry):
        response = client.get("/v1/agents", headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 401
        mock_registry.list_agents.assert_not_called()


class TestGetAgent:

    def test_get_returns_full_detail(self, client, mock_registry):
        detail = AgentDetail(
            name="coder",
            description="A coding agent",
            model="claude-sonnet-4-6",
            max_turns=25,
            max_depth=3,
            model_params=ModelParams(temperature=0.0, max_tokens=8192),
            permission=Permission(read="allow", edit="allow"),
            skills=[SkillInfo(name="clean-code", description="Code quality")],
            subagents=[
                SubagentDetail(
                    name="explorer",
                    description="Explores code",
                    model="gpt-4o",
                    max_turns=10,
                    skills=[],
                    model_params=ModelParams(),
                    permission=Permission(read="allow"),
                ),
            ],
            context=None,
        )
        mock_registry.get_agent_detail.return_value = detail
        response = client.get("/v1/agents/coder", headers=AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "coder"
        assert data["model"] == "claude-sonnet-4-6"
        assert data["max_turns"] == 25
        assert data["max_depth"] == 3
        assert data["model_params"]["temperature"] == 0.0
        assert data["model_params"]["max_tokens"] == 8192
        assert data["permission"]["read"] == "allow"
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "clean-code"
        assert len(data["subagents"]) == 1
        assert data["subagents"][0]["name"] == "explorer"
        mock_registry.get_agent_detail.assert_called_once_with("coder")

    def test_get_missing_agent_returns_404(self, client, mock_registry):
        mock_registry.get_agent_detail.return_value = None
        response = client.get("/v1/agents/unknown", headers=AUTH_HEADERS)
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["error"] == "Not Found"
        assert "unknown" in detail["detail"]

    def test_get_agent_missing_auth_returns_401(self, client, mock_registry):
        response = client.get("/v1/agents/some-agent")
        assert response.status_code == 401
        mock_registry.get_agent_detail.assert_not_called()

    def test_get_agent_with_no_description(self, client, mock_registry):
        detail = AgentDetail(
            name="minimal",
            description=None,
            model="gpt-4o-mini",
            max_turns=10,
            max_depth=3,
            model_params=ModelParams(),
            permission=None,
            skills=[],
            subagents=[],
            context=None,
        )
        mock_registry.get_agent_detail.return_value = detail
        response = client.get("/v1/agents/minimal", headers=AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["description"] is None
        assert data["permission"] is None
        assert data["context"] is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_agents.py -v`
Expected: FAIL — router still returns old `AgentInfo` shape, calls `get_template`

**Step 3: Implement router changes**

Replace `sage_api/api/agents.py` entirely:

```python
"""REST endpoints for agent discovery."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from sage_api.middleware.auth import verify_api_key
from sage_api.models.schemas import AgentDetail, AgentSummary, ErrorResponse
from sage_api.services.agent_registry import AgentRegistry

router = APIRouter(
    prefix="/v1",
    tags=["agents"],
    dependencies=[Depends(verify_api_key)],
)


def get_registry(request: Request) -> AgentRegistry:
    """Extract AgentRegistry from application state."""
    return request.app.state.registry


@router.get("/agents", response_model=list[AgentSummary])
async def list_agents(
    registry: AgentRegistry = Depends(get_registry),
) -> list[AgentSummary]:
    """List all available agents."""
    return registry.list_agents()


@router.get("/agents/{name}", response_model=AgentDetail)
async def get_agent(
    name: str,
    registry: AgentRegistry = Depends(get_registry),
) -> AgentDetail:
    """Get comprehensive agent details by name.

    Returns 404 if the agent is not found.
    """
    detail = registry.get_agent_detail(name)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="Not Found",
                detail=f"Agent '{name}' not found",
                status_code=404,
            ).model_dump(),
        )
    return detail
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api_agents.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add sage_api/api/agents.py tests/test_api_agents.py
git commit -m "feat: update agents router for AgentSummary and AgentDetail responses"
```

---

### Task 4: Migrate remaining AgentInfo consumers

**Files:**
- Modify: `sage_api/a2a/agent_card.py:8,21-25`
- Modify: `tests/test_a2a_agent_card.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_api_health.py`
- Modify: `tests/test_models.py:74-103`
- Modify: `sage_api/models/schemas.py` (remove AgentInfo alias)

**Step 1: Update A2A agent_card.py**

The `build_agent_card` function takes `list[AgentInfo]` which is now
`AgentSummary`. Update the type hint:

```python
# sage_api/a2a/agent_card.py line 8
from sage_api.models.schemas import AgentSummary

# line 21
def build_agent_card(agents: list[AgentSummary], base_url: str) -> dict:
    """Build an A2A-compliant AgentCard dict from a list of agents.

    Args:
        agents: List of AgentSummary objects from the registry.
        ...
```

**Step 2: Update all test files**

In each test file, replace `AgentInfo` imports and usages with `AgentSummary`.
The constructor calls need `model` and count fields instead of `capabilities`:

- `tests/test_a2a_agent_card.py`: Replace `AgentInfo(name=..., description=..., capabilities=[])` with `AgentSummary(name=..., description=..., model="gpt-4o-mini", skills_count=0, subagents_count=0)`
- `tests/test_main.py`: Same replacement pattern
- `tests/test_api_health.py`: Same replacement pattern
- `tests/test_models.py`: Replace `TestAgentInfo` class — update to test `AgentSummary` fields instead of `capabilities`

**Step 3: Remove AgentInfo alias from schemas.py**

Delete the `AgentInfo = AgentSummary` line added in Task 1.

**Step 4: Run full test suite**

Run: `pytest -v`
Expected: ALL PASS (no remaining references to `AgentInfo`)

**Step 5: Commit**

```bash
git add sage_api/models/schemas.py sage_api/a2a/agent_card.py \
    tests/test_a2a_agent_card.py tests/test_main.py \
    tests/test_api_health.py tests/test_models.py
git commit -m "refactor: replace AgentInfo with AgentSummary across all consumers"
```

---

### Task 5: Verify with real agent data and run full suite

**Step 1: Run the full test suite**

Run: `pytest -v --tb=short`
Expected: ALL PASS

**Step 2: Smoke-test against real agent directory**

Run a quick Python script to verify the real `agents/coder` instance produces
correct output:

```bash
source .venv/bin/activate && python3 -c "
from sage_api.services.agent_registry import AgentRegistry
registry = AgentRegistry('agents')
registry.scan()

# Test list
for a in registry.list_agents():
    print(f'Summary: {a.model_dump_json(indent=2)}')

# Test detail
detail = registry.get_agent_detail('coder')
if detail:
    print(f'Detail: {detail.model_dump_json(indent=2)}')
"
```

Expected: JSON output showing model, skills, subagents, permissions, etc.

**Step 3: Verify no regressions**

Run: `pytest -v`
Expected: ALL PASS

**Step 4: Commit (if any fixes needed)**

Only if Step 1-3 revealed issues that needed fixing.
