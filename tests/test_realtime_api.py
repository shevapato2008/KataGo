import pytest
import asyncio
import json
import os
import hashlib
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from realtime_api.main import app
from realtime_api.katago_wrapper import KataGoWrapper

# Helper to mock process
def mock_process():
    process = AsyncMock()
    # stdin.write is a synchronous method on StreamWriter, so use MagicMock
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdin.drain = AsyncMock()
    
    process.stdout = AsyncMock()
    process.stderr = AsyncMock()
    process.returncode = None
    
    # Prevent infinite loops in log readers by default: return EOF immediately
    process.stderr.readline.return_value = b""
    process.stdout.readline.return_value = b"" 
    
    # terminate() and kill() are synchronous methods on the Process object
    process.terminate = MagicMock()
    process.kill = MagicMock()
    
    return process
@pytest.mark.asyncio
async def test_katago_wrapper_lifecycle():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        process = mock_process()
        process.stdout.readline.return_value = b""
        mock_exec.return_value = process
        
        wrapper = KataGoWrapper("katago", "config", "model")
        
        await wrapper.start()
        
        assert wrapper.process is not None
        assert wrapper.running is True
        
        await wrapper.stop()
        assert wrapper.running is False
        assert wrapper.process is None

@pytest.mark.asyncio
async def test_katago_wrapper_query():
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        process = mock_process()
        
        # Prepare a response
        response_data = {"id": "test_id", "result": "ok"}
        response_line = json.dumps(response_data).encode() + b"\n"
        
        # read_loop will call readline. 
        # 1. First call: returns response
        # 2. Second call: returns b"" (EOF) to stop the loop
        process.stdout.readline.side_effect = [response_line, b""]
        mock_exec.return_value = process
        
        wrapper = KataGoWrapper("katago", "config", "model")
        await wrapper.start()
        
        # Send query
        result = await wrapper.query(
            {
                "id": "test_id",
                "_wrapper": {"selected_model": "untrusted"},
                "overrideSettings": {"model": "b18", "maxVisits": 10},
            }
        )
        
        assert result == response_data
        
        # Check that stdin was written to
        process.stdin.write.assert_called_once()
        written = process.stdin.write.call_args[0][0]
        assert b"test_id" in written
        forwarded = json.loads(written)
        assert "_wrapper" not in forwarded
        assert forwarded["overrideSettings"] == {"maxVisits": 10}
        
        await wrapper.stop()

@pytest.mark.asyncio
async def test_api_analyze_success():
    mock_wrapper = MagicMock()
    mock_wrapper.process = MagicMock()
    mock_wrapper.process.returncode = None
    expected_response = {"id": "req_1", "moveInfos": []}
    mock_wrapper.model_path = "/models/default.bin.gz"
    mock_wrapper.model_sha256 = "a" * 64
    mock_wrapper.model_sha256_verified = True
    mock_wrapper.human_model_path = None
    mock_wrapper.human_model_sha256 = None
    mock_wrapper.human_model_sha256_verified = False
    mock_wrapper.query = AsyncMock(return_value=expected_response)
    with patch.dict("realtime_api.main.wrappers", {"default": mock_wrapper}, clear=True), \
         patch("realtime_api.main.default_model_name", "default"), \
         patch("realtime_api.main.katago_version", "KataGo v1.16.3"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"id": "req_1", "moves": [["B", "Q4"]], "rules": "Chinese"}
            response = await client.post("/analyze", json=payload)
            assert response.status_code == 200
            assert response.json() == {
                **expected_response,
                "_wrapper": {
                    "selected_model": "default",
                    "model_path": "/models/default.bin.gz",
                    "model_sha256": "a" * 64,
                    "model_sha256_verified": True,
                    "human_model_path": None,
                    "human_model_sha256": None,
                    "human_model_sha256_verified": False,
                    "katago_version": "KataGo v1.16.3",
                },
            }
            mock_wrapper.query.assert_called_once()
            call_arg = mock_wrapper.query.call_args[0][0]
            assert call_arg["id"] == "req_1"
            assert call_arg["moves"] == [("B", "Q4")]
            assert "_wrapper" not in call_arg
            assert "model" not in call_arg.get("overrideSettings", {})


@pytest.mark.asyncio
async def test_api_health_check_success():
    mock_wrapper = MagicMock()
    mock_wrapper.process = MagicMock()
    mock_wrapper.process.returncode = None
    mock_wrapper.process.pid = 1234
    mock_wrapper.has_human_model = False
    mock_wrapper.model_path = "/models/test-model.bin.gz"
    mock_wrapper.model_sha256 = "b" * 64
    mock_wrapper.model_sha256_verified = True
    mock_wrapper.human_model_path = None
    mock_wrapper.human_model_sha256 = None
    mock_wrapper.human_model_sha256_verified = False
    mock_cfg = MagicMock()
    mock_cfg.katago.models = []
    with patch.dict("realtime_api.main.wrappers", {"default": mock_wrapper}, clear=True), \
         patch("realtime_api.main.default_model_name", "default"), \
         patch("realtime_api.main.app_config", mock_cfg), \
         patch("realtime_api.main.katago_version", "KataGo v1.16.3"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["capability_schema"] == 1
            assert data["katago_version"] == "KataGo v1.16.3"
            assert data["models"]["default"]["pid"] == 1234
            assert data["models"]["default"]["has_human_model"] is False
            assert data["models"]["default"]["model_path"] == "/models/test-model.bin.gz"
            assert data["models"]["default"]["model"] == "/models/test-model.bin.gz"
            assert data["models"]["default"]["model_sha256"] == "b" * 64
            assert data["models"]["default"]["human_model_path"] is None
            assert data["models"]["default"]["human_model_sha256"] is None


@pytest.mark.asyncio
async def test_api_health_check_failure():
    mock_wrapper = MagicMock()
    mock_wrapper.process = MagicMock()
    mock_wrapper.process.returncode = 1  # died
    mock_wrapper.process.pid = 1234
    mock_wrapper.has_human_model = False
    mock_wrapper.model_path = "/models/test-model.bin.gz"
    mock_wrapper.model_sha256 = "b" * 64
    mock_wrapper.model_sha256_verified = True
    mock_wrapper.human_model_path = None
    mock_wrapper.human_model_sha256 = None
    mock_wrapper.human_model_sha256_verified = False
    mock_cfg = MagicMock()
    mock_cfg.katago.models = []
    with patch.dict("realtime_api.main.wrappers", {"default": mock_wrapper}, clear=True), \
         patch("realtime_api.main.default_model_name", "default"), \
         patch("realtime_api.main.app_config", mock_cfg), \
         patch("realtime_api.main.katago_version", "KataGo v1.16.3"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["default_model"] == "default"
            assert data["models"]["default"]["running"] is False


def _mock_wrapper(response):
    w = MagicMock()
    w.process = MagicMock()
    w.process.returncode = None
    w.process.pid = 4321
    w.has_human_model = True
    w.model_path = "/models/main.bin.gz"
    w.model_sha256 = "c" * 64
    w.model_sha256_verified = True
    w.human_model_path = "/models/human.bin.gz"
    w.human_model_sha256 = "d" * 64
    w.human_model_sha256_verified = True
    w.query = AsyncMock(return_value=response)
    return w


@pytest.mark.asyncio
async def test_analyze_routes_to_requested_model():
    b28 = _mock_wrapper({"id": "r", "engine": "b28"})
    b18 = _mock_wrapper({"id": "r", "engine": "b18"})
    with patch.dict("realtime_api.main.wrappers", {"b28": b28, "b18": b18}, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"), \
         patch("realtime_api.main.katago_version", "KataGo v1.16.3"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"id": "r", "moves": [["B", "Q4"]], "overrideSettings": {"model": "b18"}}
            resp = await client.post("/analyze", json=payload)
            assert resp.status_code == 200
            b18.query.assert_called_once()
            b28.query.assert_not_called()
            # forwarded query must NOT carry the routing key
            forwarded = b18.query.call_args[0][0]
            assert "model" not in forwarded.get("overrideSettings", {})
            assert "_wrapper" not in forwarded
            assert resp.json()["_wrapper"] == {
                "selected_model": "b18",
                "model_path": "/models/main.bin.gz",
                "model_sha256": "c" * 64,
                "model_sha256_verified": True,
                "human_model_path": "/models/human.bin.gz",
                "human_model_sha256": "d" * 64,
                "human_model_sha256_verified": True,
                "katago_version": "KataGo v1.16.3",
            }


@pytest.mark.asyncio
async def test_analyze_defaults_to_default_model():
    b28 = _mock_wrapper({"id": "r"})
    b18 = _mock_wrapper({"id": "r"})
    with patch.dict("realtime_api.main.wrappers", {"b28": b28, "b18": b18}, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"), \
         patch("realtime_api.main.katago_version", "KataGo v1.16.3"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/analyze", json={"id": "r", "moves": [["B", "Q4"]]})
            assert resp.status_code == 200
            b28.query.assert_called_once()
            b18.query.assert_not_called()
            assert resp.json()["_wrapper"]["selected_model"] == "b28"
            assert resp.json()["_wrapper"]["model_sha256"] == "c" * 64
            assert resp.json()["_wrapper"]["katago_version"] == "KataGo v1.16.3"
            forwarded = b28.query.call_args.args[0]
            assert "_wrapper" not in forwarded
            assert "model" not in forwarded.get("overrideSettings", {})


@pytest.mark.asyncio
async def test_analyze_unknown_model_returns_400():
    b28 = _mock_wrapper({"id": "r"})
    with patch.dict("realtime_api.main.wrappers", {"b28": b28}, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/analyze", json={"id": "r", "overrideSettings": {"model": "bxx"}})
            assert resp.status_code == 400
            b28.query.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", ["", "   ", None, 123, ["b18"]])
async def test_analyze_malformed_model_selector_returns_400(bad_value):
    # An explicit (present) but falsy/invalid selector must NOT silently fall back to
    # default; it must be rejected with 400. Only key-absence means "use default".
    b28 = _mock_wrapper({"id": "r"})
    with patch.dict("realtime_api.main.wrappers", {"b28": b28}, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/analyze",
                json={"id": "r", "moves": [["B", "Q4"]], "overrideSettings": {"model": bad_value}},
            )
            assert resp.status_code == 400
            b28.query.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_process_death_midquery_schedules_recovery():
    # If the subprocess dies DURING query(), the handler must 503 AND lazily trigger a
    # guarded bring-up, so recovery starts immediately instead of waiting for the next
    # request's readiness check to notice the dead process. The process is ALIVE at the
    # readiness check (returncode None) and only dies inside query() — so this exercises
    # the mid-query except branch, not the pre-query readiness branch.
    b28 = _mock_wrapper({"id": "r"})  # returncode None → passes readiness check

    async def _die_midquery(*args, **kwargs):
        b28.process.returncode = 1  # observed dead after this failed query
        raise RuntimeError("KataGo process terminated")
    b28.query = AsyncMock(side_effect=_die_midquery)

    with patch.dict("realtime_api.main.wrappers", {"b28": b28}, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"), \
         patch("realtime_api.main._schedule_bring_up") as sched:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/analyze", json={"id": "r", "moves": [["B", "Q4"]]})
            assert resp.status_code == 503
            b28.query.assert_called_once()
            sched.assert_called_once_with("b28")


@pytest.mark.asyncio
async def test_analyze_strips_model_but_keeps_humanslprofile():
    b18 = _mock_wrapper({"id": "r"})
    with patch.dict("realtime_api.main.wrappers", {"b18": b18}, clear=True), \
         patch("realtime_api.main.default_model_name", "b18"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"id": "r", "overrideSettings": {"model": "b18", "humanSLProfile": "rank_5d"}}
            resp = await client.post("/analyze", json=payload)
            assert resp.status_code == 200
            ov = b18.query.call_args[0][0]["overrideSettings"]
            assert ov == {"humanSLProfile": "rank_5d"}


@pytest.mark.asyncio
async def test_health_reports_all_models():
    b28 = _mock_wrapper({"id": "r"})
    b18 = _mock_wrapper({"id": "r"})
    mock_cfg = MagicMock()
    mock_cfg.katago.models = []
    with patch.dict("realtime_api.main.wrappers", {"b28": b28, "b18": b18}, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"), \
         patch("realtime_api.main.app_config", mock_cfg), \
         patch("realtime_api.main.katago_version", "KataGo v1.16.3"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["default_model"] == "b28"
            assert set(data["models"].keys()) == {"b28", "b18"}
            for model in data["models"].values():
                assert model["running"] is True
                assert model["pid"] == 4321
                assert model["model_path"] == "/models/main.bin.gz"
                assert model["model_sha256"] == "c" * 64
                assert model["model_sha256_verified"] is True
                assert model["human_model_path"] == "/models/human.bin.gz"
                assert model["human_model_sha256"] == "d" * 64
                assert model["human_model_sha256_verified"] is True


@pytest.mark.asyncio
async def test_health_non_default_down_is_degraded_200():
    # b28 (default) running, b18 (secondary) exited → whole instance still serves default,
    # so HTTP 200 + status "degraded", and b18 is reported as not running.
    b28 = _mock_wrapper({"id": "r"})
    b18 = _mock_wrapper({"id": "r"})
    b18.process.returncode = 1  # secondary died
    mock_cfg = MagicMock()
    mock_cfg.katago.models = []
    with patch.dict("realtime_api.main.wrappers", {"b28": b28, "b18": b18}, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"), \
         patch("realtime_api.main.app_config", mock_cfg), \
         patch("realtime_api.main.katago_version", "KataGo v1.16.3"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "degraded"
            assert data["models"]["b28"]["running"] is True
            assert data["models"]["b18"]["running"] is False


@pytest.mark.asyncio
async def test_health_default_down_is_503_with_full_report():
    # b28 (default) exited → 503, but the full per-model report is still returned so
    # operators can see which models remain usable.
    b28 = _mock_wrapper({"id": "r"})
    b28.process.returncode = 1  # default died
    b18 = _mock_wrapper({"id": "r"})
    mock_cfg = MagicMock()
    mock_cfg.katago.models = []
    with patch.dict("realtime_api.main.wrappers", {"b28": b28, "b18": b18}, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"), \
         patch("realtime_api.main.app_config", mock_cfg), \
         patch("realtime_api.main.katago_version", "KataGo v1.16.3"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["default_model"] == "b28"
            assert data["models"]["b28"]["running"] is False
            assert data["models"]["b18"]["running"] is True


@pytest.mark.asyncio
async def test_health_failed_start_wrapper_reported_not_raised():
    # A wrapper whose start() failed has no process; it must appear in the report as
    # not-running (default-down → 503), never crash the endpoint.
    b28 = _mock_wrapper({"id": "r"})
    b28.process = None  # start() failed → no process
    mock_cfg = MagicMock()
    mock_cfg.katago.models = []
    with patch.dict("realtime_api.main.wrappers", {"b28": b28}, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"), \
         patch("realtime_api.main.app_config", mock_cfg), \
         patch("realtime_api.main.katago_version", "KataGo v1.16.3"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["models"]["b28"]["running"] is False
            assert data["models"]["b28"]["pid"] is None


@pytest.mark.asyncio
async def test_lifespan_builds_registry_from_legacy_config():
    import os as _os
    from unittest.mock import AsyncMock, MagicMock, patch
    from realtime_api import main as main_mod

    legacy = _os.path.join(_os.path.dirname(__file__), "test_config.yaml")

    def _fake_wrapper(*args, **kwargs):
        w = MagicMock()
        w.start = AsyncMock()
        w.stop = AsyncMock()
        w.process = MagicMock()
        w.process.returncode = None
        w.has_human_model = kwargs.get("human_model_path") is not None
        return w

    with patch.dict("realtime_api.main.wrappers", {}, clear=True), \
         patch("realtime_api.main.default_model_name", None), \
         patch.dict(_os.environ, {"KATAGO_CONFIG_FILE": legacy}), \
         patch("realtime_api.main._ensure_single_model", new=AsyncMock()), \
         patch("realtime_api.main._load_katago_version", new=AsyncMock(return_value="KataGo test")) as load_version, \
         patch("realtime_api.main.KataGoWrapper", side_effect=_fake_wrapper):
        transport = ASGITransport(app=app)
        async with LifespanManager(app):  # triggers lifespan startup/shutdown
            assert set(main_mod.wrappers.keys()) == {"default"}
            assert main_mod.default_model_name == "default"
            load_version.assert_awaited_once()


@pytest.mark.asyncio
async def test_default_serves_while_secondary_bringup_blocked():
    import os as _os, asyncio as _asyncio
    from unittest.mock import AsyncMock, MagicMock, patch
    from realtime_api import main as main_mod

    multi = _os.path.join(_os.path.dirname(__file__), "test_config_multimodel.yaml")
    block = _asyncio.Event()  # never set → b18 bring-up hangs

    async def fake_ensure(model, label):
        if "b18" in model.path:      # only b18's MAIN artifact blocks
            await block.wait()
        return "a" * 64, True

    def make_wrapper(*args, **kwargs):
        w = MagicMock()
        w.process = None
        w.has_human_model = kwargs.get("human_model_path") is not None

        async def _start():
            w.process = MagicMock()
            w.process.returncode = None
            w.process.pid = 999
        w.start = _start
        w.stop = AsyncMock()
        w.query = AsyncMock(return_value={"id": "r", "moveInfos": []})
        return w

    with patch.dict("realtime_api.main.wrappers", {}, clear=True), \
         patch("realtime_api.main.default_model_name", None), \
         patch("realtime_api.main._bringup_tasks", []), \
         patch.dict(_os.environ, {"KATAGO_CONFIG_FILE": multi}), \
         patch("realtime_api.main._ensure_single_model", new=fake_ensure), \
         patch("realtime_api.main.KataGoWrapper", side_effect=make_wrapper):
        transport = ASGITransport(app=app)
        async with LifespanManager(app):
            # default (b28) ready at yield even though b18 bring-up is still blocked
            assert main_mod.wrappers["b28"].process is not None
            assert main_mod.wrappers["b18"].process is None
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.post("/analyze", json={"id": "r", "moves": [["B", "Q4"]]})
                assert r.status_code == 200        # served by ready default b28
                r2 = await client.post(
                    "/analyze", json={"id": "r", "overrideSettings": {"model": "b18"}}
                )
                assert r2.status_code == 503       # configured but not ready (not 400)
                h = await client.get("/health")
                assert h.status_code == 200
                assert h.json()["status"] == "degraded"
        block.set()  # allow the cancelled background task to unwind


def test_artifact_lock_is_per_destination():
    from realtime_api import main as main_mod
    with patch.dict("realtime_api.main._artifact_locks", {}, clear=True):
        a = main_mod._artifact_lock("/models/humanv0.bin.gz")
        b = main_mod._artifact_lock("/models/humanv0.bin.gz")
        c = main_mod._artifact_lock("/models/b18.bin.gz")
        assert a is b        # same destination → shared lock → serialized downloads
        assert a is not c


@pytest.mark.asyncio
async def test_model_recovers_from_transient_bringup_failure():
    from unittest.mock import MagicMock, patch
    from realtime_api import main as main_mod

    m = MagicMock()
    m.name = "b18"; m.path = "/tmp/models/b18.bin.gz"; m.human_model = None; m.additional_args = []

    calls = {"n": 0}

    async def flaky_ensure(model, label):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient download failure")  # first attempt fails
        return "a" * 64, True

    def make_wrapper(mm):
        w = MagicMock()
        w.process = None

        async def _start():
            w.process = MagicMock(); w.process.returncode = None; w.process.pid = 7
        w.start = _start
        return w

    with patch.dict("realtime_api.main.wrappers", {}, clear=True), \
         patch.dict("realtime_api.main._models_by_name", {"b18": m}, clear=True), \
         patch.dict("realtime_api.main._artifact_locks", {}, clear=True), \
         patch("realtime_api.main._bringup_inflight", set()), \
         patch("realtime_api.main.app_config", MagicMock()), \
         patch("realtime_api.main._new_wrapper", side_effect=make_wrapper), \
         patch("realtime_api.main._ensure_single_model", new=flaky_ensure):
        await main_mod._supervise_bring_up("b18")            # attempt 1 → fails
        assert main_mod.wrappers["b18"].process is None
        await main_mod._supervise_bring_up("b18")            # attempt 2 → heals, no restart
        assert main_mod.wrappers["b18"].process is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch_target", ["main", "human"])
async def test_bringup_rejects_existing_model_hash_mismatch_without_download(tmp_path, mismatch_target):
    from realtime_api import main as main_mod
    from realtime_api.config import ModelConfig, NamedModelConfig

    main_path = tmp_path / "main.bin.gz"
    human_path = tmp_path / "human.bin.gz"
    main_path.write_bytes(b"actual-main")
    human_path.write_bytes(b"actual-human")
    main_sha = hashlib.sha256(main_path.read_bytes()).hexdigest()
    human_sha = hashlib.sha256(human_path.read_bytes()).hexdigest()
    if mismatch_target == "main":
        main_sha = "0" * 64
    else:
        human_sha = "0" * 64

    model = NamedModelConfig(
        name="b28",
        path=str(main_path),
        sha256=main_sha,
        auto_download=False,
        human_model=ModelConfig(path=str(human_path), sha256=human_sha, auto_download=False),
    )
    wrapper = MagicMock()
    wrapper.process = None
    wrapper.start = AsyncMock()

    with patch.dict(main_mod.wrappers, {"b28": wrapper}, clear=True):
        await main_mod._bring_up_model(model, wrapper)
        wrapper.start.assert_not_awaited()
        assert not any(w.process and w.process.returncode is None for w in main_mod.wrappers.values())


@pytest.mark.asyncio
async def test_bringup_rejects_failed_post_download_verification(tmp_path):
    from realtime_api import main as main_mod
    from realtime_api.config import NamedModelConfig

    path = tmp_path / "downloaded.bin.gz"
    model = NamedModelConfig(
        name="b28",
        path=str(path),
        url="https://example.invalid/model.bin.gz",
        sha256="0" * 64,
        auto_download=True,
    )
    wrapper = MagicMock()
    wrapper.process = None
    wrapper.start = AsyncMock()

    def fake_download(url, dest, expected):
        with open(dest, "wb") as handle:
            handle.write(b"wrong downloaded bytes")

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        with patch.dict(main_mod.wrappers, {"b28": wrapper}, clear=True), \
             patch("realtime_api.main._download_executor", executor), \
             patch("realtime_api.main._download_model", side_effect=fake_download):
            await main_mod._bring_up_model(model, wrapper)
            wrapper.start.assert_not_awaited()
            assert not any(w.process and w.process.returncode is None for w in main_mod.wrappers.values())
    finally:
        executor.shutdown(wait=True)


@pytest.mark.asyncio
async def test_katago_version_is_normalized_and_uses_runtime_library_environment():
    from realtime_api import main as main_mod

    process = MagicMock()
    process.returncode = 0
    process.communicate = AsyncMock(
        return_value=(b"KataGo v1.16.3\r\nGit revision: abc123\r\n", b"")
    )
    with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/existing"}, clear=True), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as spawn:
        version = await main_mod._load_katago_version(
            "/opt/katago", ["/runtime/a", "/runtime/b"]
        )
    assert version == "KataGo v1.16.3\nGit revision: abc123"
    spawn.assert_awaited_once()
    assert spawn.await_args.kwargs["env"]["LD_LIBRARY_PATH"] == "/runtime/a:/runtime/b:/existing"


@pytest.mark.asyncio
async def test_katago_version_timeout_terminates_then_kills_process():
    from realtime_api import main as main_mod

    blocked = asyncio.Event()

    async def block_communicate():
        await blocked.wait()

    process = MagicMock()
    process.returncode = None
    process.communicate = AsyncMock(side_effect=block_communicate)
    process.terminate = MagicMock()
    process.kill = MagicMock()
    process.wait = AsyncMock(side_effect=[asyncio.TimeoutError(), None])
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)):
        with pytest.raises(TimeoutError, match="timed out"):
            await main_mod._load_katago_version("/opt/katago", [], timeout=0.01)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.await_count == 2


@pytest.mark.asyncio
async def test_katago_version_cancellation_cleans_up_process():
    from realtime_api import main as main_mod

    blocked = asyncio.Event()

    async def block_communicate():
        await blocked.wait()

    process = MagicMock()
    process.returncode = None
    process.communicate = AsyncMock(side_effect=block_communicate)
    process.terminate = MagicMock()
    process.kill = MagicMock()
    process.wait = AsyncMock(return_value=None)
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)):
        task = asyncio.create_task(main_mod._load_katago_version("/opt/katago", []))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    process.terminate.assert_called_once()
    process.wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_katago_version_failure_prevents_lifespan_availability():
    from realtime_api import main as main_mod

    legacy = os.path.join(os.path.dirname(__file__), "test_config.yaml")
    with patch.dict(main_mod.wrappers, {}, clear=True), \
         patch.dict(os.environ, {"KATAGO_CONFIG_FILE": legacy}), \
         patch("realtime_api.main._load_katago_version", side_effect=RuntimeError("version failed")):
        async with LifespanManager(app):
            assert main_mod.wrappers == {}
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health")
                assert response.status_code == 503


def test_download_aborts_on_shutdown_event(tmp_path):
    from unittest.mock import patch
    from realtime_api import main as main_mod

    dest = str(tmp_path / "model.bin.gz")
    main_mod._shutdown_event.set()
    try:
        with patch("urllib.request.urlopen", side_effect=AssertionError("must not hit network")):
            with pytest.raises(RuntimeError, match="shutting down"):
                main_mod._download_model("http://example/x", dest, None)
    finally:
        main_mod._shutdown_event.clear()
    assert not os.path.exists(dest)


def test_shutdown_joins_download_worker_and_cleans_tmp(tmp_path):
    import threading as _threading
    from concurrent.futures import ThreadPoolExecutor
    from realtime_api import main as main_mod

    tmp_file = str(tmp_path / "model.bin.gz.tmp")
    started = _threading.Event()
    done = {"v": False}

    def fake_worker():
        open(tmp_file, "wb").close()        # simulate a partial download in progress
        started.set()
        main_mod._shutdown_event.wait()     # block mid-"download" until shutdown is signalled
        os.remove(tmp_file)                 # cooperative cleanup on abort
        done["v"] = True

    main_mod._shutdown_event.clear()
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        ex.submit(fake_worker)
        assert started.wait(timeout=5)      # worker is now blocked with .tmp present
        assert os.path.exists(tmp_file)

        # This is what lifespan shutdown does: signal, then join.
        main_mod._shutdown_event.set()
        ex.shutdown(wait=True)              # MUST block until the worker thread exits

        assert done["v"] is True           # join actually waited for termination
        assert not os.path.exists(tmp_file)  # .tmp cleaned before shutdown returned
    finally:
        main_mod._shutdown_event.clear()


@pytest.mark.asyncio
async def test_lifespan_cleanup_runs_on_cancellation():
    import os as _os
    from unittest.mock import AsyncMock, MagicMock, patch
    from realtime_api import main as main_mod

    multi = _os.path.join(_os.path.dirname(__file__), "test_config_multimodel.yaml")
    shutdown_calls = {"n": 0}

    class FakeExecutor:
        def __init__(self, *a, **k): pass
        def submit(self, *a, **k): pass
        def shutdown(self, wait=True): shutdown_calls["n"] += 1

    def make_wrapper(*a, **k):
        w = MagicMock()
        w.process = MagicMock(); w.process.returncode = None; w.process.pid = 5
        w.start = AsyncMock(); w.stop = AsyncMock()
        return w

    with patch.dict("realtime_api.main.wrappers", {}, clear=True), \
         patch("realtime_api.main.default_model_name", None), \
         patch("realtime_api.main._bringup_tasks", []), \
         patch("realtime_api.main._download_executor", None), \
         patch.dict(_os.environ, {"KATAGO_CONFIG_FILE": multi}), \
         patch("realtime_api.main.ThreadPoolExecutor", FakeExecutor), \
         patch("realtime_api.main._ensure_single_model", new=AsyncMock()), \
         patch("realtime_api.main._new_wrapper", side_effect=make_wrapper):
        cm = main_mod.lifespan(app)
        await cm.__aenter__()                       # run startup to the yield
        assert set(main_mod.wrappers) == {"b28", "b18"}
        # Inject cancellation at the yield; the finally MUST still run. Per
        # contextlib's @asynccontextmanager contract, __aexit__ re-raising the SAME
        # exception instance it was given is reported by returning False (not
        # suppressed) rather than raising it directly out of __aexit__ itself — the
        # re-raise into the enclosing scope is normally performed by the `async with`
        # statement machinery, which isn't in play when __aexit__ is invoked directly.
        result = await cm.__aexit__(asyncio.CancelledError, asyncio.CancelledError(), None)
        assert result is False                      # cancellation not suppressed
        assert shutdown_calls["n"] >= 1             # executor JOIN happened despite cancel
        assert main_mod.wrappers == {}              # registry cleared in finally
