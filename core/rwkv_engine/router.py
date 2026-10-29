"""
Hybrid Routing — local RWKV with an optional cloud second opinion.

One convention everywhere: a score is a **risk** in ``[0, 100]``
(``0`` = looks fine, ``100`` = looks hallucinated).

Routing is decided on **uncertainty**, not on the level of the score: a score
far from the middle (< 35 or > 65) is decisive and stays local; a score in
the uncertain band is the only case worth a second opinion.

Cloud status: **not implemented.**  ``CLOUD_IMPLEMENTED`` is ``False`` and no
request is ever sent, whatever the environment contains.  The hooks
(``HALLUGUARD_CLOUD_API_KEY``) are reserved for a
future implementation; when implemented it will send *code* to a third party,
which contradicts the "code never leaves the machine" guarantee and must be
an explicit opt-in.

Routes: ``local`` (valid local score), ``cloud`` (reserved),
``heuristic_only`` (no valid score; the scorer ignores the RWKV source and
redistributes its weight).
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from core.rwkv_engine import inference as rwkv_inference

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────
#: Scores inside this closed band are "uncertain" and eligible for escalation.
UNCERTAIN_BAND: tuple[float, float] = (35.0, 65.0)
CLOUD_IMPLEMENTED: bool = False
_ENV_CLOUD_KEY = "HALLUGUARD_CLOUD_API_KEY"
_ENV_LOG_SIZE = "HALLUGUARD_ROUTING_LOG_SIZE"


def _log_size() -> int:
    try:
        return max(1, int(os.environ.get(_ENV_LOG_SIZE, "1000")))
    except ValueError:
        return 1000


# ── Routing decision log (bounded, kept in memory for benchmarks) ──
_routing_log: deque[dict[str, Any]] = deque(maxlen=_log_size())
_warned_cloud = False


@dataclass
class RoutingDecision:
    """Record of a single routing decision."""
    rwkv_score: float | None
    route: str  # "local", "cloud", "heuristic_only"
    cloud_score: float | None = None
    final_score: float | None = None  # None = no valid score
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


def _cloud_available() -> bool:
    """True only if a cloud call is both implemented and configured."""
    global _warned_cloud
    configured = bool(os.environ.get(_ENV_CLOUD_KEY))
    if configured and not CLOUD_IMPLEMENTED and not _warned_cloud:
        logger.warning(
            "%s is set but cloud routing is not implemented: ignored "
            "(no code is sent anywhere).", _ENV_CLOUD_KEY,
        )
        _warned_cloud = True
    return configured and CLOUD_IMPLEMENTED


def _call_cloud_llm(code: str) -> float | None:
    """
    Reserved extension point for a cloud second opinion.

    Not implemented: always returns ``None``.  Never sends anything.
    """
    del code
    return None


def score(code: str) -> RoutingDecision:
    """
    Score a code snippet using the hybrid routing strategy.

    Args:
        code: Raw source code string.

    Returns:
        A ``RoutingDecision`` recording the scores and route taken.
    """
    start = time.perf_counter()
    rwkv_score = rwkv_inference.score_code_snippet(code)

    if rwkv_score is None:
        decision = RoutingDecision(
            rwkv_score=None, route="heuristic_only", final_score=None
        )
    else:
        decision = RoutingDecision(
            rwkv_score=rwkv_score, route="local", final_score=rwkv_score
        )
        lo, hi = UNCERTAIN_BAND
        if lo <= rwkv_score <= hi and _cloud_available():
            cloud_score = _call_cloud_llm(code)
            if cloud_score is not None:
                decision.route = "cloud"
                decision.cloud_score = cloud_score
                decision.final_score = cloud_score

    decision.latency_ms = (time.perf_counter() - start) * 1000

    _routing_log.append({
        "rwkv_score": decision.rwkv_score,
        "route": decision.route,
        "cloud_score": decision.cloud_score,
        "final_score": decision.final_score,
        "latency_ms": round(decision.latency_ms, 2),
        "timestamp": decision.timestamp,
    })
    logger.info(
        "Routing decision: route=%s rwkv=%s final=%s (%.1f ms)",
        decision.route, decision.rwkv_score, decision.final_score,
        decision.latency_ms,
    )
    return decision


def get_routing_log() -> list[dict[str, Any]]:
    """Return a copy of the (bounded) routing decision log."""
    return list(_routing_log)


def clear_routing_log() -> None:
    """Clear the routing decision log."""
    _routing_log.clear()
