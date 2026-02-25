"""A2A integration."""

from sage_api.a2a.agent_card import build_agent_card, router as agent_card_router
from sage_api.a2a.routes import router as a2a_router

__all__ = ["agent_card_router", "a2a_router", "build_agent_card"]
