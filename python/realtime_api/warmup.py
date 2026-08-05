"""Startup warmup for one KataGo model.

Why this exists: on a Mali-class GPU (RK3562/RK3576) the first query of each kind
pays the OpenCL kernel compile, which can take a minute or more. Serving that cost
to the first real user looks like a hang, so every model is driven through one
1-visit normal query (and, when it has a human model, one 1-visit human query)
before it is advertised as ready. The phase is reported on /health, and the
SmartBox launcher renders it as engine-warmup progress
(setup-wizard/app/services/launcher.py::_go_health_probe).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Final


STABLE_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "engine_start_failed",
        "normal_warmup_timeout",
        "normal_warmup_invalid",
        "human_model_missing",
        "human_warmup_timeout",
        "human_warmup_invalid",
        "engine_exited",
    }
)


class WarmupPhase(str, Enum):
    STARTING = "starting"
    WARMING_NORMAL = "warming_normal"
    WARMING_HUMAN = "warming_human"
    READY = "ready"
    FAILED = "failed"


#: WARMING_NORMAL -> READY exists only for a model configured WITHOUT a human model
#: (e.g. a search-only b28 on a multi-model server). A model that declares a human
#: model still has to walk through WARMING_HUMAN, so a missing/broken humanPolicy is
#: a warmup failure rather than a silently skipped phase.
_ALLOWED_TRANSITIONS: Final[dict[WarmupPhase, frozenset[WarmupPhase]]] = {
    WarmupPhase.STARTING: frozenset({WarmupPhase.WARMING_NORMAL}),
    WarmupPhase.WARMING_NORMAL: frozenset({WarmupPhase.WARMING_HUMAN, WarmupPhase.READY}),
    WarmupPhase.WARMING_HUMAN: frozenset({WarmupPhase.READY}),
}


@dataclass
class WarmupStatus:
    phase: WarmupPhase = WarmupPhase.STARTING
    error_code: str | None = field(default=None, init=False)

    def transition(self, phase: WarmupPhase) -> None:
        if phase not in _ALLOWED_TRANSITIONS.get(self.phase, frozenset()):
            raise ValueError("invalid warmup phase transition")
        self.phase = phase

    def fail(self, error_code: str) -> None:
        if self.phase in (WarmupPhase.READY, WarmupPhase.FAILED):
            raise ValueError("terminal warmup status cannot change")
        if error_code not in STABLE_ERROR_CODES:
            raise ValueError("unknown warmup error code")
        self.phase = WarmupPhase.FAILED
        self.error_code = error_code


def profile_for_rank(human_kyu_rank: float, modern_style: bool) -> str:
    rounded_rank = round(human_kyu_rank)
    style = "rank" if modern_style else "preaz"
    rank = f"{1 - rounded_rank}d" if rounded_rank <= 0 else f"{rounded_rank}k"
    return f"{style}_{rank}"


def normal_query() -> dict[str, Any]:
    return {
        "id": "warmup-normal",
        "moves": [],
        "initialStones": [],
        "rules": "Chinese",
        "komi": 7.5,
        "boardXSize": 19,
        "boardYSize": 19,
        "analyzeTurns": [0],
        "includePolicy": True,
        "includeOwnership": False,
        "maxVisits": 1,
        "priority": 0,
    }


def human_query() -> dict[str, Any]:
    query = normal_query()
    query["id"] = "warmup-human"
    query["overrideSettings"] = {
        "humanSLProfile": profile_for_rank(0, True),
        "ignorePreRootHistory": False,
    }
    return query


def _has_nonempty_list(result: Mapping[str, Any], field_name: str) -> bool:
    value = result.get(field_name)
    return isinstance(value, list) and bool(value)


def _has_move_infos(result: Mapping[str, Any]) -> bool:
    value = result.get("moveInfos")
    return isinstance(value, list) and all(isinstance(item, Mapping) for item in value)


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _has_finite_policy(result: Mapping[str, Any], field_name: str) -> bool:
    return _has_nonempty_list(result, field_name) and all(
        _is_finite_number(item) for item in result[field_name]
    )


def validate_normal_result(result: object) -> bool:
    return (
        isinstance(result, Mapping)
        and _has_move_infos(result)
        and _has_finite_policy(result, "policy")
    )


def validate_human_result(result: object) -> bool:
    return (
        isinstance(result, Mapping)
        and validate_normal_result(result)
        and _has_finite_policy(result, "humanPolicy")
    )


async def run_full_warmup(
    wrapper: Any,
    status: WarmupStatus,
    timeout: float | None = None,
    expects_human: bool = True,
) -> None:
    """Drive one model to READY (or FAILED). Never raises for engine-side problems.

    ``expects_human`` says whether this model is CONFIGURED with a human model. When it
    is, a wrapper that reports no loaded human model is a failure (the configured
    副网 never came up) rather than a phase to skip.
    """
    normal_timeout = 90.0 if timeout is None else timeout
    human_timeout = 45.0 if timeout is None else timeout

    status.transition(WarmupPhase.WARMING_NORMAL)
    try:
        normal_result = await wrapper.query(normal_query(), timeout=normal_timeout)
    except TimeoutError:
        status.fail("normal_warmup_timeout")
        return
    except Exception:
        status.fail("engine_exited")
        return

    if not validate_normal_result(normal_result):
        status.fail("normal_warmup_invalid")
        return

    if not expects_human:
        # Search-only model: there is no humanPolicy to warm, and demanding one would
        # keep the model out of service forever.
        status.transition(WarmupPhase.READY)
        return

    try:
        has_human_model = wrapper.has_human_model
    except Exception:
        status.fail("engine_exited")
        return
    if not has_human_model:
        status.fail("human_model_missing")
        return

    status.transition(WarmupPhase.WARMING_HUMAN)
    try:
        human_result = await wrapper.query(human_query(), timeout=human_timeout)
    except TimeoutError:
        status.fail("human_warmup_timeout")
        return
    except Exception:
        status.fail("engine_exited")
        return

    if not validate_human_result(human_result):
        status.fail("human_warmup_invalid")
        return
    status.transition(WarmupPhase.READY)
