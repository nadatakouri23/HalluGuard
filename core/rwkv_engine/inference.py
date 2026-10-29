"""
RWKV Inference Engine.

Signal
------
The score is derived from the model's **log-probabilities**, not from text it
generates.  The code is fed token by token through the (recurrent) model and
the negative log-likelihood of every actual next token is accumulated:

    mean_nll = - 1/(N-1) * sum_i log p(token_{i+1} | token_{<=i})

Code a language model finds surprising (an invented API name, an unlikely
call) has a higher mean NLL.  The NLL is mapped to a **risk** in ``[0, 100]``
(``0`` = looks fine, ``100`` = looks hallucinated) by a logistic function whose
``midpoint`` and ``scale`` come from a calibration file, because the raw NLL
depends on the model and on the corpus:

    {"midpoint": 2.1, "scale": 0.45}      # HALLUGUARD_RWKV_CALIBRATION

Without calibration the signal is **withheld** (``None``) unless
``HALLUGUARD_RWKV_UNCALIBRATED=1`` explicitly opts in, so an unvalidated
number never silently drives the verdict.  Inference is deterministic (no
sampling).  Any failure returns ``None`` — never an invented value.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.rwkv_engine import model_loader

logger = logging.getLogger(__name__)

ENV_CALIBRATION = "HALLUGUARD_RWKV_CALIBRATION"
ENV_ALLOW_UNCALIBRATED = "HALLUGUARD_RWKV_UNCALIBRATED"
ENV_MAX_TOKENS = "HALLUGUARD_RWKV_MAX_TOKENS"

DEFAULT_MAX_TOKENS = 384
#: Placeholder mapping used ONLY when the user opts into uncalibrated scoring.
DEFAULT_CALIBRATION = (2.0, 0.5)


@dataclass
class RwkvResult:
    """Outcome of one RWKV scoring run."""
    score: float | None      # risk in [0, 100], None if unavailable/withheld
    nll: float | None = None   # mean negative log-likelihood per token (nats)
    n_tokens: int = 0
    calibrated: bool = False
    latency_ms: float = 0.0


def _max_tokens() -> int:
    try:
        return max(2, int(os.environ.get(ENV_MAX_TOKENS, DEFAULT_MAX_TOKENS)))
    except ValueError:
        return DEFAULT_MAX_TOKENS


def load_calibration(path: str | Path | None = None) -> tuple[float, float] | None:
    """Read ``(midpoint, scale)`` from the calibration file, if any."""
    candidate = Path(path or os.environ.get(ENV_CALIBRATION, "models/rwkv_calibration.json"))
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
        mid, scale = float(data["midpoint"]), float(data["scale"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (mid, scale) if scale > 0 else None


def nll_to_risk(nll: float, midpoint: float, scale: float) -> float:
    """Logistic map from mean NLL to a ``[0, 100]`` risk."""
    z = (nll - midpoint) / scale
    z = max(-60.0, min(60.0, z))
    return 100.0 / (1.0 + math.exp(-z))


def _log_prob(logits: Any, index: int) -> float:
    """Log-softmax of *logits* at *index* (torch, numpy or plain sequence)."""
    try:
        import torch  # type: ignore[import-not-found,unused-ignore]

        if isinstance(logits, torch.Tensor):
            return float(torch.log_softmax(logits.float(), dim=-1)[index])
    except ImportError:
        pass
    try:
        import numpy as np  # type: ignore[import-not-found,unused-ignore]

        arr = np.asarray(logits, dtype=np.float64)
        top = arr.max()
        return float(arr[index] - top - np.log(np.exp(arr - top).sum()))
    except ImportError:
        pass
    vals = [float(x) for x in logits]
    top = max(vals)
    return vals[index] - top - math.log(sum(math.exp(v - top) for v in vals))


def mean_nll(model: Any, pipeline: Any, code: str, max_tokens: int) -> tuple[float, int] | None:
    """
    Mean per-token NLL of *code* under *model*, or ``None`` if too short.

    The model is run one token at a time, carrying the recurrent state, so
    every position yields a distribution over the next token.
    """
    tokens = list(pipeline.encode(code.strip()))[:max_tokens]
    if len(tokens) < 2:
        return None
    state = None
    total = 0.0
    for i in range(len(tokens) - 1):
        logits, state = model.forward([tokens[i]], state)
        total -= _log_prob(logits, tokens[i + 1])
    count = len(tokens) - 1
    return total / count, count


def analyze_code(code: str) -> RwkvResult:
    """Score *code* and report how the number was obtained."""
    model = model_loader.get_model()
    pipeline = model_loader.get_pipeline()
    if model is None or pipeline is None:
        logger.debug("RWKV model not available.")
        return RwkvResult(score=None)

    start = time.perf_counter()
    try:
        measured = mean_nll(model, pipeline, code, _max_tokens())
    except Exception as exc:  # noqa: BLE001 - inference must never break analysis
        logger.error("RWKV inference failed: %s", exc)
        return RwkvResult(score=None)
    elapsed_ms = (time.perf_counter() - start) * 1000
    if measured is None:
        return RwkvResult(score=None, latency_ms=elapsed_ms)
    nll, count = measured

    calibration = load_calibration()
    calibrated = calibration is not None
    if calibration is None:
        if os.environ.get(ENV_ALLOW_UNCALIBRATED, "").strip().lower() not in ("1", "true", "yes"):
            logger.info(
                "RWKV NLL=%.3f computed but no calibration file: signal withheld "
                "(set %s or %s).", nll, ENV_CALIBRATION, ENV_ALLOW_UNCALIBRATED,
            )
            return RwkvResult(score=None, nll=nll, n_tokens=count, latency_ms=elapsed_ms)
        calibration = DEFAULT_CALIBRATION

    risk = nll_to_risk(nll, *calibration)
    logger.info("RWKV inference: nll=%.3f risk=%.1f (%d tokens, %.0f ms)",
                nll, risk, count, elapsed_ms)
    return RwkvResult(score=risk, nll=nll, n_tokens=count,
                      calibrated=calibrated, latency_ms=elapsed_ms)


def score_code_snippet(code: str) -> float | None:
    """
    Risk score in ``[0, 100]`` for *code* (``0`` fine, ``100`` hallucinated).

    Returns ``None`` when the model is unavailable, inference failed, or the
    signal is uncalibrated and not explicitly allowed.
    """
    return analyze_code(code).score


def _parse_score(raw_output: str) -> float | None:
    """
    Extract a ``[0, 100]`` risk from an LLM's *textual* answer (used by remote
    scorers).  Accepts a JSON number, a JSON object with a known key
    (``risk_score``, ``score``, ``hallucination_score``; ``validity`` is
    inverted) or a JSON list of such objects (averaged).  Returns ``None``
    when nothing reliable can be read — never a made-up default.
    """
    try:
        data = json.loads(raw_output.strip())
    except ValueError:
        return None

    def _one(item: Any) -> float | None:
        if isinstance(item, bool):
            return None
        if isinstance(item, (int, float)):
            return max(0.0, min(100.0, float(item)))
        if isinstance(item, dict):
            for key in ("risk_score", "score", "hallucination_score", "validity"):
                if key in item:
                    try:
                        val = float(item[key])
                    except (TypeError, ValueError):
                        return None
                    if key == "validity":
                        val = 100.0 - val
                    return max(0.0, min(100.0, val))
        return None

    if isinstance(data, list):
        values = [v for v in (_one(i) for i in data) if v is not None]
        return sum(values) / len(values) if values else None
    return _one(data)
