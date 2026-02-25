from __future__ import annotations

import asyncio
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from sage_api.services.agent_registry import AgentRegistry
from sage_api.services.hot_reload import AgentHotReloader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_registry() -> MagicMock:
    """Return a mock AgentRegistry with a no-op reload()."""
    registry = MagicMock(spec=AgentRegistry)
    registry.reload = MagicMock()
    return registry


@contextmanager
def inject_awatch(fake_awatch_fn):
    """Context manager that temporarily replaces AgentHotReloader._awatch_factory."""
    original = AgentHotReloader._awatch_factory
    AgentHotReloader._awatch_factory = staticmethod(lambda: fake_awatch_fn)  # type: ignore[assignment]
    try:
        yield
    finally:
        AgentHotReloader._awatch_factory = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_start_stop_lifecycle() -> None:
    """Reloader starts, reports is_running=True, stops cleanly."""
    reloader = AgentHotReloader()
    registry = build_registry()

    # Patch awatch with a generator that never yields (blocks until cancelled)
    async def never_yields(*_args, **_kwargs):
        while True:
            await asyncio.sleep(3600)
            yield  # pragma: no cover

    with inject_awatch(never_yields):
        await reloader.start("/agents", registry)
        assert reloader.is_running is True

        await reloader.stop()
        assert reloader.is_running is False


async def test_md_file_change_triggers_reload() -> None:
    """A change to an .md file causes registry.reload() to be called once."""
    reloader = AgentHotReloader()
    registry = build_registry()

    changes = [
        (1, "/agents/AGENTS.md"),
    ]
    reload_called = asyncio.Event()

    def side_effect_reload() -> None:
        reload_called.set()

    registry.reload.side_effect = side_effect_reload

    async def fake_awatch(*_args, **_kwargs):
        yield changes
        # Stall so the task stays alive until stop() is called
        await asyncio.sleep(3600)  # pragma: no cover

    with inject_awatch(fake_awatch):
        await reloader.start("/agents", registry)

        # Wait for reload to be called (with generous timeout)
        await asyncio.wait_for(reload_called.wait(), timeout=2.0)
        registry.reload.assert_called_once()

        await reloader.stop()


async def test_non_md_change_does_not_trigger_reload() -> None:
    """Changes to non-.md files (e.g., .py, .json) must NOT call reload()."""
    reloader = AgentHotReloader()
    registry = build_registry()

    non_md_changes = [
        (1, "/agents/config.json"),
        (1, "/agents/script.py"),
        (1, "/agents/README.txt"),
    ]
    # After non-md batch, set a sentinel so we know the loop processed the batch
    sentinel = asyncio.Event()

    async def fake_awatch(*_args, **_kwargs):
        yield non_md_changes
        sentinel.set()
        await asyncio.sleep(3600)  # pragma: no cover

    with inject_awatch(fake_awatch):
        await reloader.start("/agents", registry)

        await asyncio.wait_for(sentinel.wait(), timeout=2.0)
        # Give one extra event-loop iteration for any stray calls
        await asyncio.sleep(0)

        registry.reload.assert_not_called()

        await reloader.stop()


async def test_double_start_is_idempotent() -> None:
    """Calling start() twice does not spawn a second task."""
    reloader = AgentHotReloader()
    registry = build_registry()

    async def never_yields(*_args, **_kwargs):
        while True:
            await asyncio.sleep(3600)
            yield  # pragma: no cover

    with inject_awatch(never_yields):
        await reloader.start("/agents", registry)
        first_task = reloader._task

        await reloader.start("/agents", registry)  # second call — no-op
        second_task = reloader._task

        assert first_task is second_task, "start() must not create a new task when already running"

        await reloader.stop()


async def test_mixed_changes_only_reloads_for_md() -> None:
    """A batch with both .md and non-.md files triggers exactly one reload."""
    reloader = AgentHotReloader()
    registry = build_registry()

    mixed_changes = [
        (1, "/agents/AGENTS.md"),
        (1, "/agents/config.json"),
        (2, "/agents/notes.md"),
    ]
    reload_called = asyncio.Event()

    def side_effect_reload() -> None:
        reload_called.set()

    registry.reload.side_effect = side_effect_reload

    async def fake_awatch(*_args, **_kwargs):
        yield mixed_changes
        await asyncio.sleep(3600)  # pragma: no cover

    with inject_awatch(fake_awatch):
        await reloader.start("/agents", registry)

        await asyncio.wait_for(reload_called.wait(), timeout=2.0)
        # One reload per batch, not one per file
        registry.reload.assert_called_once()

        await reloader.stop()


async def test_stop_when_not_running_is_safe() -> None:
    """Calling stop() on a reloader that was never started must not raise."""
    reloader = AgentHotReloader()
    assert reloader.is_running is False
    await reloader.stop()  # Should not raise
    assert reloader.is_running is False


async def test_reload_exception_does_not_crash_watcher() -> None:
    """If registry.reload() raises, the watcher loop must keep running."""
    reloader = AgentHotReloader()
    registry = build_registry()
    registry.reload.side_effect = RuntimeError("disk full")

    second_batch_seen = asyncio.Event()

    async def fake_awatch(*_args, **_kwargs):
        yield [(1, "/agents/AGENTS.md")]
        yield [(1, "/agents/other.md")]
        second_batch_seen.set()
        await asyncio.sleep(3600)  # pragma: no cover

    with inject_awatch(fake_awatch):
        await reloader.start("/agents", registry)

        await asyncio.wait_for(second_batch_seen.wait(), timeout=2.0)
        # reload was called at least for both batches (despite exception)
        assert registry.reload.call_count >= 2

        await reloader.stop()
