"""Warmup phase reporting on /health.

The SmartBox launcher (setup-wizard/app/services/launcher.py::_go_health_probe) reads
three states off this endpoint and shows the user a different screen for each:

    200 + phase "ready"        + ready true   -> Go mode is usable
    503 + phase "warming_*"    + ready false  -> engine warmup progress
    anything else                             -> still starting

These tests hold that contract, and hold that a model is never advertised as ready
before it has actually answered a query.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from realtime_api.main import app
from realtime_api.warmup import (
    WarmupPhase,
    WarmupStatus,
    run_full_warmup,
    validate_human_result,
    validate_normal_result,
)


WARM_RESULT = {"id": "r", "moveInfos": [], "policy": [0.5, 0.5], "humanPolicy": [0.5, 0.5]}


def _wrapper(running=True):
    w = MagicMock()
    w.process = MagicMock() if running else None
    if running:
        w.process.returncode = None
        w.process.pid = 4321
    w.has_human_model = True
    w.model_path = "/models/main.bin.gz"
    w.model_sha256 = "c" * 64
    w.model_sha256_verified = True
    w.human_model_path = "/models/human.bin.gz"
    w.human_model_sha256 = "d" * 64
    w.human_model_sha256_verified = True
    w.query = AsyncMock(return_value=WARM_RESULT)
    return w


def _status(*phases, error_code=None):
    status = WarmupStatus()
    for phase in phases:
        status.transition(phase)
    if error_code is not None:
        status.fail(error_code)
    return status


async def _health(statuses, wrappers=None):
    wrappers = wrappers if wrappers is not None else {"b28": _wrapper()}
    cfg = MagicMock()
    cfg.katago.models = []
    with patch.dict("realtime_api.main.wrappers", wrappers, clear=True), \
         patch.dict("realtime_api.main.warmup_statuses", statuses, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"), \
         patch("realtime_api.main.app_config", cfg), \
         patch("realtime_api.main.katago_version", "KataGo v1.16.3"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", [WarmupPhase.WARMING_NORMAL, WarmupPhase.WARMING_HUMAN])
async def test_a_warming_default_model_is_503_and_says_which_phase(phase):
    phases = (
        (WarmupPhase.WARMING_NORMAL,)
        if phase is WarmupPhase.WARMING_NORMAL
        else (WarmupPhase.WARMING_NORMAL, WarmupPhase.WARMING_HUMAN)
    )
    resp = await _health({"b28": _status(*phases)})
    assert resp.status_code == 503
    body = resp.json()
    assert body["phase"] == phase.value
    assert body["ready"] is False
    # The engine is up and its identity is already attested — the launcher shows
    # warmup progress rather than an error, and a capability reader can still read it.
    assert body["capability_schema"] == 1
    assert body["models"]["b28"]["running"] is True


@pytest.mark.asyncio
async def test_a_model_nobody_warmed_is_never_reported_ready():
    # No status entry at all (e.g. a wrapper installed outside the bring-up path):
    # fail closed to "starting" rather than inheriting a ready-looking default.
    resp = await _health({})
    assert resp.status_code == 503
    assert resp.json()["phase"] == "starting"
    assert resp.json()["ready"] is False


@pytest.mark.asyncio
async def test_a_failed_warmup_reports_its_error_code():
    resp = await _health({"b28": _status(WarmupPhase.WARMING_NORMAL, error_code="normal_warmup_timeout")})
    assert resp.status_code == 503
    body = resp.json()
    assert body["phase"] == "failed"
    assert body["error_code"] == "normal_warmup_timeout"
    assert body["ready"] is False


@pytest.mark.asyncio
async def test_a_process_that_died_after_warming_is_reported_failed_not_ready():
    # The state machine still says READY; the process is gone. The live process wins.
    resp = await _health(
        {"b28": _status(WarmupPhase.WARMING_NORMAL, WarmupPhase.WARMING_HUMAN, WarmupPhase.READY)},
        wrappers={"b28": _wrapper(running=False)},
    )
    assert resp.status_code == 503
    body = resp.json()
    assert body["phase"] == "failed"
    assert body["error_code"] == "engine_exited"
    assert body["models"]["b28"]["warm"] is False


@pytest.mark.asyncio
async def test_a_warm_default_serves_even_while_a_secondary_is_still_warming():
    resp = await _health(
        {
            "b28": _status(WarmupPhase.WARMING_NORMAL, WarmupPhase.WARMING_HUMAN, WarmupPhase.READY),
            "b18": _status(WarmupPhase.WARMING_NORMAL),
        },
        wrappers={"b28": _wrapper(), "b18": _wrapper()},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body["phase"], body["ready"]) == ("ready", True)
    assert body["models"]["b18"]["warmup_phase"] == "warming_normal"
    assert body["models"]["b18"]["warm"] is False


@pytest.mark.asyncio
async def test_warmup_runs_in_the_background_so_health_answers_during_it():
    """The port's whole point: the port must be OPEN while the model warms.

    If warmup were awaited inside startup, the launcher would see connection-refused
    ("starting") for the entire OpenCL compile instead of warmup progress.
    """
    import os

    release = asyncio.Event()
    legacy = os.path.join(os.path.dirname(__file__), "test_config.yaml")

    def make_wrapper(*args, **kwargs):
        w = _wrapper(running=False)

        async def _start():
            w.process = MagicMock()
            w.process.returncode = None
            w.process.pid = 999

        async def _query(query, timeout=None):
            await release.wait()  # warmup blocks until the test lets it finish
            return WARM_RESULT

        w.start = _start
        w.stop = AsyncMock()
        w.query = _query
        return w

    with patch.dict("realtime_api.main.wrappers", {}, clear=True), \
         patch.dict("realtime_api.main.warmup_statuses", {}, clear=True), \
         patch("realtime_api.main.default_model_name", None), \
         patch("realtime_api.main._bringup_tasks", []), \
         patch.dict(os.environ, {"KATAGO_CONFIG_FILE": legacy}), \
         patch("realtime_api.main._ensure_single_model", new=AsyncMock(return_value=("a" * 64, True))), \
         patch("realtime_api.main._load_katago_version", new=AsyncMock(return_value="KataGo test")), \
         patch("realtime_api.main.KataGoWrapper", side_effect=make_wrapper):
        transport = ASGITransport(app=app)
        async with LifespanManager(app):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                warming = await client.get("/health")
                assert warming.status_code == 503
                assert warming.json()["phase"] == "warming_normal"
                assert warming.json()["ready"] is False

                release.set()
                for _ in range(200):
                    resp = await client.get("/health")
                    if resp.json()["ready"] is True:
                        break
                    await asyncio.sleep(0.01)
                assert resp.status_code == 200
                assert resp.json()["phase"] == "ready"


@pytest.mark.asyncio
async def test_a_model_without_a_human_model_becomes_ready_without_a_human_query():
    """A search-only model (no human副网 configured) must not wait for humanPolicy.

    Demanding one would park such a model at FAILED/human_model_missing forever, which
    is what a naive port of the single-model board warmup would have done.
    """
    status = WarmupStatus()
    wrapper = _wrapper()
    wrapper.has_human_model = False
    await run_full_warmup(wrapper, status, timeout=1.0, expects_human=False)
    assert status.phase is WarmupPhase.READY
    assert wrapper.query.await_count == 1  # normal only, no human query


@pytest.mark.asyncio
async def test_a_configured_human_model_that_never_loaded_is_a_failure():
    status = WarmupStatus()
    wrapper = _wrapper()
    wrapper.has_human_model = False  # configured, but the副网 is not loaded
    await run_full_warmup(wrapper, status, timeout=1.0, expects_human=True)
    assert (status.phase, status.error_code) == (WarmupPhase.FAILED, "human_model_missing")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply,expected",
    [
        ({"id": "r", "moveInfos": []}, "normal_warmup_invalid"),  # no policy
        ({"id": "r", "moveInfos": [], "policy": [0.5]}, "human_warmup_invalid"),  # no humanPolicy
    ],
)
async def test_an_engine_that_answers_garbage_does_not_count_as_warm(reply, expected):
    status = WarmupStatus()
    wrapper = _wrapper()
    wrapper.query = AsyncMock(return_value=reply)
    await run_full_warmup(wrapper, status, timeout=1.0, expects_human=True)
    assert (status.phase, status.error_code) == (WarmupPhase.FAILED, expected)


@pytest.mark.asyncio
async def test_a_query_timeout_is_reported_as_a_timeout_not_a_crash():
    status = WarmupStatus()
    wrapper = _wrapper()
    wrapper.query = AsyncMock(side_effect=TimeoutError("timed out"))
    await run_full_warmup(wrapper, status, timeout=0.01, expects_human=True)
    assert (status.phase, status.error_code) == (WarmupPhase.FAILED, "normal_warmup_timeout")


def test_policy_validation_rejects_non_finite_numbers():
    assert validate_normal_result({"moveInfos": [], "policy": [0.5]}) is True
    assert validate_normal_result({"moveInfos": [], "policy": [float("nan")]}) is False
    assert validate_normal_result({"moveInfos": [], "policy": []}) is False
    assert validate_human_result({"moveInfos": [], "policy": [0.5], "humanPolicy": [0.5]}) is True
    assert validate_human_result({"moveInfos": [], "policy": [0.5]}) is False


def test_terminal_status_cannot_be_walked_back():
    status = _status(WarmupPhase.WARMING_NORMAL, WarmupPhase.WARMING_HUMAN, WarmupPhase.READY)
    with pytest.raises(ValueError):
        status.fail("engine_exited")
    with pytest.raises(ValueError):
        status.transition(WarmupPhase.WARMING_NORMAL)
