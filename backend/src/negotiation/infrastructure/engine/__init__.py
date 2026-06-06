"""Neutral engine sub-modules.

The monolithic neutral_engine.py (1580+ lines) is decomposed here into
focused sub-modules. The parent neutral_engine.py continues to work as
the primary import — this package provides additional entry points for
testing and maintenance.

Sub-modules:
  - convergence: Agreement detection and ZOPA computation
  - transcript: Conversation history management
"""

from src.negotiation.infrastructure.neutral_engine import NeutralEngine

__all__ = ["NeutralEngine"]
