from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from sage_api.services.agent_registry import AgentRegistry

from sage_api.logging import get_logger

logger = get_logger(__name__)


def _get_awatch() -> Callable[..., Any]:
    """Lazy-load watchfiles.awatch to avoid import errors if watchfiles is absent."""
    from watchfiles import awatch  # type: ignore[import-untyped]

    return awatch


class AgentHotReloader:
    """Watches an agents directory and reloads the registry on `.md` file changes.

    Usage::

        reloader = AgentHotReloader()
        await reloader.start(agents_dir="/path/to/agents", registry=registry)
        # … later …
        await reloader.stop()
    """

    # Class-level hook — replace in tests to inject a fake awatch implementation.
    _awatch_factory: Callable[..., Any] = staticmethod(_get_awatch)  # type: ignore[assignment]

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        """Return True if the background watcher task is active and not done."""
        return self._task is not None and not self._task.done()

    async def start(self, agents_dir: str, registry: AgentRegistry) -> None:
        """Start the background file-watch task.

        Calling ``start()`` when the watcher is already running is idempotent —
        the existing task is kept and a new one is **not** spawned.

        Args:
            agents_dir: Absolute or relative path to the directory that contains
                agent ``.md`` files.
            registry: The :class:`AgentRegistry` instance whose
                :meth:`~AgentRegistry.reload` method will be called on changes.
        """
        if self.is_running:
            logger.debug("AgentHotReloader.start() called but watcher is already running — no-op")
            return

        self._task = asyncio.create_task(
            self._watch(agents_dir, registry),
            name="agent-hot-reload-watcher",
        )
        logger.info("AgentHotReloader started watching %s", agents_dir)

    async def stop(self) -> None:
        """Cancel the background watcher task and await its completion.

        Safe to call even when the watcher is not running.
        """
        if self._task is None or self._task.done():
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            logger.info("AgentHotReloader stopped")

    async def _watch(self, agents_dir: str, registry: AgentRegistry) -> None:
        """Internal coroutine that runs the watchfiles event loop.

        Filters events to ``.md`` and ``.toml`` files only and calls
        ``registry.reload()`` via ``asyncio.to_thread`` (blocking I/O off the event loop).
        """
        awatch = self._awatch_factory()
        watch_path = Path(agents_dir)
        logger.debug("AgentHotReloader: entering awatch loop on %s", watch_path)

        async for changes in awatch(watch_path):
            md_changes = [(change_type, path) for change_type, path in changes if Path(path).suffix in {".md", ".toml"}]
            if not md_changes:
                continue

            logger.info(
                "AgentHotReloader: detected %d config change(s), reloading registry",
                len(md_changes),
            )
            try:
                await asyncio.to_thread(registry.reload)
            except Exception:  # noqa: BLE001
                logger.exception("AgentHotReloader: registry.reload() raised an exception")
