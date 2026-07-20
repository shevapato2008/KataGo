# realtime_api 多模型服务 (b28 + b18 + humanSL) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `realtime_api` host multiple KataGo models from one yaml and route each `/analyze` request to a chosen model (b28/b18) via an `overrideSettings.model` field, while existing single-model behavior stays byte-identical.

**Architecture:** A KataGo `analysis` process holds exactly one main net (+ one optional human net), so b28 and b18 run as two separate subprocesses. `config.py` grows a `models[]` list + `default_model` (accepting the legacy single-`model` yaml unchanged); `main.py`'s lifespan starts one `KataGoWrapper` per model into a `name→wrapper` registry; `/analyze` pops `overrideSettings.model` to pick the wrapper (stripping it before forwarding), defaulting to `default_model`; `/health` reports every model.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, pytest + pytest-asyncio, httpx `ASGITransport`. Server launched with `PYTHONPATH=python python3 -m realtime_api.main`.

## Global Constraints

- **Backward compatibility is mandatory.** The legacy single-`model:` yaml (`tests/test_config.yaml`, `config.sbc.yaml`) MUST load unchanged, and any existing `/analyze` request that carries no `overrideSettings.model` MUST route to `default_model` — behavior byte-identical to today.
- **Routing key = `overrideSettings.model`** (value ∈ `models[].name`). It MUST be popped/stripped before the query is forwarded to the katago subprocess (katago rejects unknown override keys). `overrideSettings.humanSLProfile` MUST be preserved and forwarded.
- **Strict routing-selector validation.** Distinguish *key absent* from *explicit value*. Key absent → route to `default_model`. An explicit `model` that is `null`, empty, whitespace-only, non-string, or names no configured model → **HTTP 400** (`available: [...]`). Never silently fall back to another net on a malformed selector (a falsy value must NOT be treated as "absent").
- **Schema strictness (config load).** When `models[]` is supplied, `default_model` is **required** (do not silently pick the first element) and MUST name a configured model; duplicate `models[].name` is rejected. The legacy single-`model:` form is the ONLY form that synthesizes a `default` entry. A config that supplies BOTH `models[]` and a legacy `model:` is **rejected** as ambiguous.
- **Per-model startup isolation.** All wrappers are **constructed up front** (so every configured name is routable immediately; a configured-but-not-yet-started model answers **503**, and only genuinely unknown names answer 400). The **default model is brought up synchronously** so it is ready the instant the app starts serving (`lifespan` `yield`); **every secondary is brought up in a background task**. Consequently the **default's readiness never depends on any secondary** — a b18 stuck for ~17 min in download retries (`_download_model` retries 10× with exponential backoff) or a permanently-broken b18 leaves b28 fully functional and serving. Each bring-up runs under its own exception boundary (never aborts the app). Preparation of a **shared** artifact (the `humanv0` net used by both models) is serialized by a **per-destination async lock** so two bring-ups never race on the same temp file.
- **Per-model CLI args.** `additional_args` may be set **per model** on `NamedModelConfig` (appended to the katago-level `additional_args` for that model only) — the real lever to split the two nets across GPUs/devices. Empty by default → behavior unchanged.
- **`/health` readiness policy.** Always build the COMPLETE per-model report (never early-return mid-loop). Derive HTTP status explicitly: **503 iff the default model is unavailable**; otherwise **200** with `status: "ok"` when all models run, or `status: "degraded"` when a *non-default* model is down. A wrapper whose `start()` failed (no process) counts as unavailable and MUST appear in the report, not raise.
- **humanSL semantics (corrected).** humanSL is served by whichever wrapper the request routes to. Byte-identical humanSL behavior is guaranteed ONLY on the **default (b28) wrapper**, which is where all existing humanSL traffic lands (those requests carry no `overrideSettings.model`). Attaching `humanv0` to the b18 process is a NEW capability (`model:"b18"` + `humanSLProfile`); because the engine's search can blend human policy with the main net's search, humanSL play on b18 MAY differ from b28 and is **not** relied upon for back-compat and **not** calibrated here (see §8). Do NOT claim humanSL is independent of the main net.
- **Exact model coordinates, copied verbatim** (do not retype from memory):
  - b28: path `./models/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz`, url `https://media.katagotraining.org/uploaded/networks/models/kata1/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz`, sha256 `798da8fe3e9819f09535240b1bc29cb3047a4fa981433c56c491e57007a3d3f0`
  - b18: path `./models/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz`, url `https://media.katagotraining.org/uploaded/networks/models/kata1/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz`, sha256 `9d7a6afed8ff5b74894727e156f04f0cd36060a24824892008fbb6e0cba51f1d`
  - humanv0: path `./models/b18c384nbt-humanv0.bin.gz`, url `https://github.com/lightvector/KataGo/releases/download/v1.15.0/b18c384nbt-humanv0.bin.gz`, sha256 `637746e44f0efe00ad1245a50aa9bbf0716efe364c43965ead97bd6835d84ab5`
- **Out of scope:** `config.sbc.yaml` / kiosk (stays b6c96), any KaTrain-repo change, new `--mode`, calibration. Do NOT touch `MODE_CONFIG_MAP` or the `--mode` argparse.
- **Test runner:** `PYTHONPATH=python pytest <file> -v` from the repo root.
- Follow existing code style in `python/realtime_api/` (plain logging, no new deps).

---

## File Structure

- **`python/realtime_api/config.py`** (modify) — add `NamedModelConfig`, `KataGoConfig.models` + `default_model`, a `model_validator` that migrates the legacy `model`/`human_model` into `models[]` and mirrors the default back onto the legacy fields; extend `load_config` path resolution to every model.
- **`python/realtime_api/main.py`** (modify) — replace the single `katago_wrapper` global with a `wrappers: Dict[str, KataGoWrapper]` registry + `default_model_name`; build it in `lifespan`; add `_pop_route_model` + routing in `/analyze`; multi-model `/health`.
- **`config.yaml`** (modify) — server config becomes two models: b28 (default) + b18.
- **`tests/test_config.py`** (create) — config schema + back-compat + validation tests.
- **`tests/test_config_multimodel.yaml`** (create) — fixture with two named models.
- **`tests/test_realtime_api.py`** (modify) — update the 3 tests that patch `katago_wrapper`; add routing tests.
- **`README.md`, `AGENTS.md`** (modify) — document `overrideSettings.model` routing + multi-model `/health`.

Task order: **1 (config schema) → 2 (main.py registry+routing) → 3 (config.yaml + smoke) → 4 (docs).** Each task leaves the app runnable and tests green.

---

### Task 1: Config schema — `models[]` + `default_model` (legacy-compatible)

**Files:**
- Modify: `python/realtime_api/config.py`
- Create: `tests/test_config_multimodel.yaml`
- Create: `tests/test_config.py`
- Keep (unchanged, used as back-compat fixture): `tests/test_config.yaml`

**Interfaces:**
- Produces: `NamedModelConfig(ModelConfig)` with fields `name: str`, `human_model: Optional[ModelConfig]`. `KataGoConfig.models: List[NamedModelConfig]`, `KataGoConfig.default_model: str`. Legacy `KataGoConfig.model: Optional[ModelConfig]` and `KataGoConfig.human_model: Optional[ModelConfig]` remain and always mirror the default model (so Task 1 does not break the current `main.py`). `load_config(path)` returns an `AppConfig` whose every `models[].path` and `models[].human_model.path` are resolved absolute.

- [ ] **Step 1: Write the multi-model fixture**

Create `tests/test_config_multimodel.yaml`:

```yaml
katago:
  path: "/Users/fan/Repositories/KataGo/cpp/katago"
  config_path: "/Users/fan/Repositories/KataGo/cpp/configs/analysis_example.cfg"
  models:
    - name: b28
      path: "/tmp/models/b28.bin.gz"
      sha256: "798da8fe3e9819f09535240b1bc29cb3047a4fa981433c56c491e57007a3d3f0"
      human_model:
        path: "/tmp/models/humanv0.bin.gz"
    - name: b18
      path: "/tmp/models/b18.bin.gz"
      sha256: "9d7a6afed8ff5b74894727e156f04f0cd36060a24824892008fbb6e0cba51f1d"
      human_model:
        path: "/tmp/models/humanv0.bin.gz"
  default_model: b28
api:
  host: "127.0.0.1"
  port: 8000
  reload: false
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_config.py`:

```python
import os
import pytest
from pydantic import ValidationError

from realtime_api.config import load_config

HERE = os.path.dirname(__file__)
MULTI = os.path.join(HERE, "test_config_multimodel.yaml")
LEGACY = os.path.join(HERE, "test_config.yaml")


def test_multimodel_config_loads_named_models():
    cfg = load_config(MULTI)
    names = [m.name for m in cfg.katago.models]
    assert names == ["b28", "b18"]
    assert cfg.katago.default_model == "b28"
    # per-model human_model present and resolved absolute
    b18 = next(m for m in cfg.katago.models if m.name == "b18")
    assert b18.human_model is not None
    assert os.path.isabs(b18.path)
    assert os.path.isabs(b18.human_model.path)


def test_default_model_mirrored_onto_legacy_fields():
    # legacy accessors keep working: .model / .human_model == the default (b28) model
    cfg = load_config(MULTI)
    b28 = next(m for m in cfg.katago.models if m.name == "b28")
    assert cfg.katago.model is not None
    assert cfg.katago.model.path == b28.path
    assert cfg.katago.human_model is not None
    assert cfg.katago.human_model.path == b28.human_model.path


def test_legacy_single_model_config_still_loads():
    cfg = load_config(LEGACY)
    assert [m.name for m in cfg.katago.models] == ["default"]
    assert cfg.katago.default_model == "default"
    assert cfg.katago.model is not None  # legacy accessor intact
    assert os.path.isabs(cfg.katago.models[0].path)


def test_default_model_must_name_an_existing_model(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  models:\n"
        "    - {name: b28, path: /tmp/b28.bin.gz}\n"
        "  default_model: nope\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_duplicate_model_names_rejected(tmp_path):
    bad = tmp_path / "dup.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  models:\n"
        "    - {name: b28, path: /tmp/b28.bin.gz}\n"
        "    - {name: b28, path: /tmp/b28b.bin.gz}\n"
        "  default_model: b28\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_default_model_required_when_models_present(tmp_path):
    # models[] given but default_model omitted → reject (no silent first-element pick).
    bad = tmp_path / "nodefault.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  models:\n"
        "    - {name: b28, path: /tmp/b28.bin.gz}\n"
        "    - {name: b18, path: /tmp/b18.bin.gz}\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_mixed_legacy_and_models_rejected(tmp_path):
    # supplying BOTH models[] and a legacy model: is ambiguous → reject.
    bad = tmp_path / "mixed.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  model: {path: /tmp/legacy.bin.gz}\n"
        "  models:\n"
        "    - {name: b28, path: /tmp/b28.bin.gz}\n"
        "  default_model: b28\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_mixed_legacy_human_model_and_models_rejected(tmp_path):
    # models[] combined with a legacy top-level human_model: is also ambiguous → reject
    # (this is the case an after-only validator would silently overwrite).
    bad = tmp_path / "mixed_human.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  human_model: {path: /tmp/legacy-human.bin.gz}\n"
        "  models:\n"
        "    - {name: b28, path: /tmp/b28.bin.gz}\n"
        "  default_model: b28\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_empty_models_list_rejected(tmp_path):
    # An explicit empty models: [] is a malformed/partial config → reject (an
    # after-validator would misread it as legacy form).
    bad = tmp_path / "empty_models.yaml"
    bad.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  models: []\n"
        "  default_model: b28\n"
    )
    with pytest.raises(ValidationError):
        load_config(str(bad))


def test_per_model_additional_args_default_empty_and_parsed(tmp_path):
    # per-model additional_args defaults to [] and is parsed when supplied.
    good = tmp_path / "extra.yaml"
    good.write_text(
        "katago:\n"
        "  path: /x/katago\n"
        "  config_path: /x/a.cfg\n"
        "  models:\n"
        "    - {name: b28, path: /tmp/b28.bin.gz}\n"
        "    - name: b18\n"
        "      path: /tmp/b18.bin.gz\n"
        "      additional_args: ['-override-config', 'cudaDeviceToUseThread0=1']\n"
        "  default_model: b28\n"
    )
    cfg = load_config(str(good))
    b28 = next(m for m in cfg.katago.models if m.name == "b28")
    b18 = next(m for m in cfg.katago.models if m.name == "b18")
    assert b28.additional_args == []
    assert b18.additional_args == ["-override-config", "cudaDeviceToUseThread0=1"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=python pytest tests/test_config.py -v`
Expected: FAIL (e.g. `AttributeError: 'KataGoConfig' object has no attribute 'models'` / `default_model`).

- [ ] **Step 4: Implement the schema + validator**

In `python/realtime_api/config.py`, change the import line and the `KataGoConfig` model. Replace:

```python
from pydantic import BaseModel, Field
```
with:
```python
from pydantic import BaseModel, Field, model_validator
```

Add `NamedModelConfig` right after the existing `ModelConfig` class:

```python
class NamedModelConfig(ModelConfig):
    name: str
    human_model: Optional[ModelConfig] = None
    # Optional per-model extra CLI args, APPENDED to the katago-level additional_args
    # for THIS model only. This is the real lever for splitting the two nets across
    # devices (e.g. ["-override-config", "cudaDeviceToUseThread0=1"]); empty by default,
    # so behavior is unchanged unless a config opts in.
    additional_args: List[str] = Field(default_factory=list)
```

Replace the `KataGoConfig` class with:

```python
class KataGoConfig(BaseModel):
    path: str
    config_path: str
    models: List[NamedModelConfig] = Field(default_factory=list)
    default_model: Optional[str] = None
    # Legacy single-model accessors: accepted as INPUT (old yaml) and always kept
    # mirroring the default model as OUTPUT, so pre-existing readers keep working.
    model: Optional[ModelConfig] = None
    human_model: Optional[ModelConfig] = None
    additional_args: List[str] = Field(default_factory=list)
    ld_library_paths: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _reject_mixed_schema(cls, data):
        # Detect the schema FORM from raw-input KEY PRESENCE (an after-validator cannot
        # distinguish an omitted `models` key from an explicit `models: []`). Reject any
        # ambiguous/partially-migrated config up front.
        if isinstance(data, dict):
            has_models = "models" in data
            has_legacy = "model" in data or "human_model" in data
            if has_models and has_legacy:
                raise ValueError(
                    "katago config must not mix 'models' with legacy 'model'/'human_model'; use one form"
                )
            if has_models and not data.get("models"):
                raise ValueError("katago.models, when present, must be a non-empty list")
        return data

    @model_validator(mode="after")
    def _normalize_models(self) -> "KataGoConfig":
        # By here the before-validator guarantees exactly one form: legacy (`model`, no
        # `models` key) OR new (non-empty `models`, no legacy fields).
        if not self.models:
            # Legacy form: wrap the single model into a one-element list named "default".
            # This is the ONLY branch that synthesizes a default entry.
            if self.model is None:
                raise ValueError("katago config must define either 'models' or a legacy 'model'")
            self.models = [
                NamedModelConfig(
                    name="default",
                    path=self.model.path,
                    url=self.model.url,
                    auto_download=self.model.auto_download,
                    sha256=self.model.sha256,
                    human_model=self.human_model,
                )
            ]
            self.default_model = "default"
            return self
        # New form: require an explicit default_model (do NOT silently pick the first
        # element — reordering the yaml would otherwise silently change legacy routing).
        names = [m.name for m in self.models]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate model names in katago.models: {names}")
        if self.default_model is None:
            raise ValueError("katago.default_model is required when 'models' is supplied")
        if self.default_model not in names:
            raise ValueError(f"default_model '{self.default_model}' not in models {names}")
        default = next(m for m in self.models if m.name == self.default_model)
        # Mirror the default onto the legacy accessors so pre-existing readers keep working.
        self.model = ModelConfig(
            path=default.path, url=default.url, auto_download=default.auto_download, sha256=default.sha256
        )
        self.human_model = default.human_model
        return self
```

- [ ] **Step 5: Extend path resolution in `load_config`**

In `load_config`, replace the block that currently resolves `config.katago.model.path` and `config.katago.human_model.path` (the `config.katago.model.path = _resolve_path(...)` lines through the human_model `if`) with per-model resolution, then re-mirror the default:

```python
    config.katago.path = _resolve_path(base_dir, config.katago.path)
    config.katago.config_path = _resolve_path(base_dir, config.katago.config_path)
    for m in config.katago.models:
        m.path = _resolve_path(base_dir, m.path)
        if m.human_model:
            m.human_model.path = _resolve_path(base_dir, m.human_model.path)
    # keep the legacy accessors pointing at the (now resolved) default model
    default = next(m for m in config.katago.models if m.name == config.katago.default_model)
    if config.katago.model:
        config.katago.model.path = default.path
    if config.katago.human_model and default.human_model:
        config.katago.human_model.path = default.human_model.path
    config.katago.ld_library_paths = [
        _resolve_path(base_dir, path) for path in config.katago.ld_library_paths
    ]
    return config
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=python pytest tests/test_config.py -v`
Expected: PASS (11 tests).

- [ ] **Step 7: Confirm no regression in the wider suite**

Run: `PYTHONPATH=python pytest tests/test_realtime_api.py tests/test_realtime_api_full.py -v`
Expected: PASS (main.py still uses the mirrored `config.katago.model` — unchanged behavior).

- [ ] **Step 8: Commit**

```bash
git add python/realtime_api/config.py tests/test_config.py tests/test_config_multimodel.yaml
git commit -m "feat(realtime_api): config models[] + default_model with legacy single-model back-compat"
```

---

### Task 2: Multi-wrapper registry + `/analyze` routing + `/health`

**Files:**
- Modify: `python/realtime_api/main.py`
- Modify: `tests/test_realtime_api.py`

**Interfaces:**
- Consumes: `AppConfig.katago.models: List[NamedModelConfig]`, `AppConfig.katago.default_model: str` (Task 1).
- Produces: module globals `wrappers: Dict[str, KataGoWrapper]`, `default_model_name: Optional[str]`, `_models_by_name: dict`, `_bringup_tasks: list`, `_bringup_inflight: set`, `_artifact_locks: dict`, `_shutdown_event: threading.Event`, sentinel `_MODEL_KEY_ABSENT`; helpers `_new_wrapper(m) -> KataGoWrapper`, `_supervise_bring_up(name) -> None` (guarded, dedup'd, installs a fresh wrapper and recovers a failed/dead model without app restart), `_schedule_bring_up(name)` (fire-and-forget lazy heal from `/analyze`), `_bring_up_model(m, wrapper) -> None` (ensure+start under own boundary; never raises except `CancelledError`), `_ensure_artifact(model, label)` / `_artifact_lock(path)` (per-destination serialization), `_pop_route_model(query)` (pops `overrideSettings.model`; returns `_MODEL_KEY_ABSENT` if absent, else the raw value to validate). `_download_model` gains cooperative-cancel checks on `_shutdown_event` and runs on the joinable `_download_executor`; shutdown JOINs that pool (`shutdown(wait=True)`) so no download thread outlives lifespan. `/analyze` routes with strict 400 (invalid/unknown) vs 503 (configured-but-not-ready, and lazily re-triggers bring-up); `/health` returns `{"status", "default_model", "models": {name: {pid, running, returncode, has_human_model, model}}}` with HTTP 503 iff the default model is unavailable.

- [ ] **Step 1: Write the failing routing tests**

Add to `tests/test_realtime_api.py` (top-level imports already include `MagicMock, AsyncMock, patch`, `AsyncClient, ASGITransport`, `app`):

```python
def _mock_wrapper(response):
    w = MagicMock()
    w.process = MagicMock()
    w.process.returncode = None
    w.process.pid = 4321
    w.has_human_model = True
    w.query = AsyncMock(return_value=response)
    return w


@pytest.mark.asyncio
async def test_analyze_routes_to_requested_model():
    b28 = _mock_wrapper({"id": "r", "engine": "b28"})
    b18 = _mock_wrapper({"id": "r", "engine": "b18"})
    with patch.dict("realtime_api.main.wrappers", {"b28": b28, "b18": b18}, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"):
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


@pytest.mark.asyncio
async def test_analyze_defaults_to_default_model():
    b28 = _mock_wrapper({"id": "r"})
    b18 = _mock_wrapper({"id": "r"})
    with patch.dict("realtime_api.main.wrappers", {"b28": b28, "b18": b18}, clear=True), \
         patch("realtime_api.main.default_model_name", "b28"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/analyze", json={"id": "r", "moves": [["B", "Q4"]]})
            assert resp.status_code == 200
            b28.query.assert_called_once()
            b18.query.assert_not_called()


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
         patch("realtime_api.main.app_config", mock_cfg):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["default_model"] == "b28"
            assert set(data["models"].keys()) == {"b28", "b18"}


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
         patch("realtime_api.main.app_config", mock_cfg):
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
         patch("realtime_api.main.app_config", mock_cfg):
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
         patch("realtime_api.main.app_config", mock_cfg):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["models"]["b28"]["running"] is False
            assert data["models"]["b28"]["pid"] is None
```

- [ ] **Step 2: Update the 3 legacy tests that patch `katago_wrapper`**

In `tests/test_realtime_api.py`, the existing `test_api_analyze_success`, `test_api_health_check_success`, `test_api_health_check_failure` patch `realtime_api.main.katago_wrapper` (which no longer exists after this task). Convert each to the registry.

`test_api_analyze_success` — replace its `with patch(...)` line and body setup:

```python
async def test_api_analyze_success():
    mock_wrapper = MagicMock()
    mock_wrapper.process = MagicMock()
    mock_wrapper.process.returncode = None
    expected_response = {"id": "req_1", "moveInfos": []}
    mock_wrapper.query = AsyncMock(return_value=expected_response)
    with patch.dict("realtime_api.main.wrappers", {"default": mock_wrapper}, clear=True), \
         patch("realtime_api.main.default_model_name", "default"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"id": "req_1", "moves": [["B", "Q4"]], "rules": "Chinese"}
            response = await client.post("/analyze", json=payload)
            assert response.status_code == 200
            assert response.json() == expected_response
            mock_wrapper.query.assert_called_once()
            call_arg = mock_wrapper.query.call_args[0][0]
            assert call_arg["id"] == "req_1"
            assert call_arg["moves"] == [("B", "Q4")]
```

`test_api_health_check_success`:

```python
async def test_api_health_check_success():
    mock_wrapper = MagicMock()
    mock_wrapper.process = MagicMock()
    mock_wrapper.process.returncode = None
    mock_wrapper.process.pid = 1234
    mock_wrapper.has_human_model = False
    mock_wrapper.model_path = "/models/test-model.bin.gz"
    mock_cfg = MagicMock()
    mock_cfg.katago.models = []
    with patch.dict("realtime_api.main.wrappers", {"default": mock_wrapper}, clear=True), \
         patch("realtime_api.main.default_model_name", "default"), \
         patch("realtime_api.main.app_config", mock_cfg):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["models"]["default"]["pid"] == 1234
            assert data["models"]["default"]["has_human_model"] is False
```

`test_api_health_check_failure`:

```python
async def test_api_health_check_failure():
    mock_wrapper = MagicMock()
    mock_wrapper.process = MagicMock()
    mock_wrapper.process.returncode = 1  # died
    mock_cfg = MagicMock()
    mock_cfg.katago.models = []
    with patch.dict("realtime_api.main.wrappers", {"default": mock_wrapper}, clear=True), \
         patch("realtime_api.main.default_model_name", "default"), \
         patch("realtime_api.main.app_config", mock_cfg):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["default_model"] == "default"
            assert data["models"]["default"]["running"] is False
```

- [ ] **Step 2b: Convert EVERY other test file that patches the removed `katago_wrapper` global**

Removing `realtime_api.main.katago_wrapper` breaks three more files that patch it (verified via `grep -rln katago_wrapper tests/`): `tests/test_human_model.py`, `tests/test_realtime_api_bounds.py`, `tests/test_realtime_api_multitenancy.py`. Each uses the same idiom — `with patch("realtime_api.main.katago_wrapper", new_callable=MagicMock) as mock_wrapper:`. Apply the SAME registry conversion everywhere.

**Mechanical rule (analyze tests — `bounds`, `multitenancy`):** replace the single `with patch(...)` context-manager line with the two-patch registry form, keeping the mock body and assertions unchanged:

```python
    mock_wrapper = MagicMock()
    mock_wrapper.start = AsyncMock()
    mock_wrapper.stop = AsyncMock()
    mock_wrapper.process = MagicMock()
    mock_wrapper.process.returncode = None
    # ... existing mock_wrapper.query / expected_response setup unchanged ...
    with patch.dict("realtime_api.main.wrappers", {"default": mock_wrapper}, clear=True), \
         patch("realtime_api.main.default_model_name", "default"):
        transport = ASGITransport(app=app)
        # ... rest of the test body unchanged ...
```

**`tests/test_human_model.py` — the two `/health` tests** (`test_api_health_check_with_human_model`, `test_api_health_check_without_human_model`) also assert the OLD flat `/health` shape (`json_resp["has_human_model"]`). Convert BOTH the patching and the assertions. Full replacement for `test_api_health_check_with_human_model` (mirror it for the `without` variant with `has_human_model=False`):

```python
async def test_api_health_check_with_human_model():
    mock_wrapper = MagicMock()
    mock_wrapper.start = AsyncMock()
    mock_wrapper.stop = AsyncMock()
    mock_wrapper.process = MagicMock()
    mock_wrapper.process.returncode = None
    mock_wrapper.process.pid = 1234
    mock_wrapper.has_human_model = True
    mock_cfg = MagicMock()
    mock_cfg.katago.models = []
    with patch.dict("realtime_api.main.wrappers", {"default": mock_wrapper}, clear=True), \
         patch("realtime_api.main.default_model_name", "default"), \
         patch("realtime_api.main.app_config", mock_cfg):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            json_resp = response.json()
            assert json_resp["status"] == "ok"
            assert json_resp["models"]["default"]["has_human_model"] is True
```

(The two `KataGoWrapper`-level tests in `test_human_model.py` — `test_katago_wrapper_with_human_model` / `without` — patch `asyncio.create_subprocess_exec`, NOT the global, so they need no change.)

- [ ] **Step 2c: Add a legacy single-model lifespan test (registry built from a real legacy config)**

Add to `tests/test_realtime_api.py` — this exercises the actual `lifespan` bring-up path with a legacy single-`model:` config (not just a hand-patched registry), guarding the back-compat contract end-to-end. It stubs `KataGoWrapper` and `_ensure_single_model` so no real subprocess/download happens:

```python
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
         patch("realtime_api.main.KataGoWrapper", side_effect=_fake_wrapper):
        transport = ASGITransport(app=app)
        async with LifespanManager(app):  # triggers lifespan startup/shutdown
            assert set(main_mod.wrappers.keys()) == {"default"}
            assert main_mod.default_model_name == "default"
```

This test needs `asgi-lifespan` (dev-only). Add the import at the top of the file: `from asgi_lifespan import LifespanManager`. If `asgi-lifespan` is not already available, add it to `requirements-api.txt` (dev dependency) in this step's commit. Confirm it is installed with `pip install asgi-lifespan` before running.

- [ ] **Step 2d: Prove default serves while a secondary bring-up is BLOCKED (startup-isolation invariant)**

This is the test that pins the invariant "default readiness never depends on a secondary." It loads the two-model fixture, blocks b18's artifact prep forever, and asserts the app still starts, serves b28, answers 503 (not 400) for the not-ready b18, and reports `degraded`/200:

```python
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
```

- [ ] **Step 2e: Guard the shared-artifact dedup lock**

The shared `humanv0` race is prevented by (a) bringing the default up fully before any secondary starts and (b) a per-destination async lock. Add a small regression test locking the lock's identity semantics (same path → same lock, different path → different lock):

```python
def test_artifact_lock_is_per_destination():
    from realtime_api import main as main_mod
    with patch.dict("realtime_api.main._artifact_locks", {}, clear=True):
        a = main_mod._artifact_lock("/models/humanv0.bin.gz")
        b = main_mod._artifact_lock("/models/humanv0.bin.gz")
        c = main_mod._artifact_lock("/models/b18.bin.gz")
        assert a is b        # same destination → shared lock → serialized downloads
        assert a is not c
```

- [ ] **Step 2f: A model recovers from a transient bring-up failure WITHOUT an app restart**

Proves the guarded supervisor heals a model whose first bring-up failed (Codex round-3 finding #2): the first attempt fails (model stays not-ready → 503), a second attempt (as `/analyze` would lazily trigger) installs a fresh wrapper and succeeds:

```python
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
```

- [ ] **Step 2g: A download aborts cooperatively when shutdown is signalled**

Proves `_download_model` honors `_shutdown_event` so a shutdown does not orphan the executor worker (Codex round-3 finding #1). With the event set, it aborts before touching the network and leaves no destination file:

```python
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
```

(Ensure `import os` is present at the top of `tests/test_realtime_api.py`.)

- [ ] **Step 2h: Shutdown JOINS the download worker (no orphaned thread, `.tmp` cleaned)**

Proves the shutdown protocol waits for a mid-download worker to actually terminate before returning, and that the worker's cooperative-abort cleans its `<dest>.tmp` (Codex round-4 finding). This exercises the exact join primitive the lifespan uses (`executor.shutdown(wait=True)`) against a worker blocked mid-download until the event fires:

```python
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
```

- [ ] **Step 2i: Lifespan cleanup (executor JOIN + registry clear) runs even on CANCELLATION**

Proves the `try/finally` guarantees cleanup when a cancellation is injected at the yield point — the abnormal-exit path a bare `yield` would skip (Codex round-5 finding). It drives the real `lifespan` context manager and throws `CancelledError` into it, then asserts the executor was joined and the registry cleared:

```python
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
        # Inject cancellation at the yield; the finally MUST still run.
        with pytest.raises(asyncio.CancelledError):
            await cm.__aexit__(asyncio.CancelledError, asyncio.CancelledError(), None)
        assert shutdown_calls["n"] >= 1             # executor JOIN happened despite cancel
        assert main_mod.wrappers == {}              # registry cleared in finally
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONPATH=python pytest tests/test_realtime_api.py -v`
Expected: FAIL (`realtime_api.main` has no attribute `wrappers` / `default_model_name`; `/health` has no `models` key).

- [ ] **Step 4: Implement the registry, routing, and health in `main.py`**

Add `JSONResponse` to the FastAPI imports at the top of the file (needed so `/health` can return a 503 that still carries the full report body):

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
```

Replace the globals (lines 22-23):

Also add these imports at the top of the file: `import threading` (cooperative-cancel flag read from the download worker thread) and `from concurrent.futures import ThreadPoolExecutor` (a dedicated, *joinable* download pool — the default executor cannot be joined at shutdown).

```python
wrappers: dict[str, KataGoWrapper] = {}
default_model_name: Optional[str] = None
app_config: Optional[AppConfig] = None
_models_by_name: dict = {}         # name -> NamedModelConfig (for lazy re-bring-up)
_bringup_tasks: list = []          # background/lazy bring-up tasks (awaited on shutdown)
_bringup_inflight: set = set()     # model names with a bring-up currently running (dedup)
_artifact_locks: dict = {}         # dest path -> asyncio.Lock (serialize shared downloads)
_download_executor: Optional[ThreadPoolExecutor] = None  # dedicated, joinable download pool
# threading.Event (not asyncio) because it is polled from the download worker thread. Set
# on shutdown so a blocked/retrying download aborts cooperatively — cancelling the asyncio
# task alone cannot stop the executor thread.
_shutdown_event = threading.Event()

# Sentinel distinguishing "overrideSettings.model absent" (→ use default) from an
# explicit-but-invalid value (→ 400). Never equal to any client-supplied value.
_MODEL_KEY_ABSENT = object()
```

Replace the `lifespan` body (the part from `if katago_wrapper is not None:` through the `yield` / shutdown). The design that actually satisfies "default readiness never depends on a secondary": **construct every wrapper up front** (so every configured name is routable immediately — a not-yet-started model returns 503, not 400), **bring the default model up synchronously** (so it is ready the instant `lifespan` reaches `yield`), then **bring up each secondary in a background task** so a slow/broken secondary cannot hold the app in startup. A per-destination async lock serializes preparation of the **shared** `humanv0` artifact so two bring-ups never race on the same `<dest>.tmp` / `os.replace`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global wrappers, default_model_name, app_config, _models_by_name, _bringup_tasks
    global _download_executor

    if wrappers:
        yield
        return

    config_path = os.getenv("KATAGO_CONFIG_FILE") or get_default_config_path()
    try:
        app_config = load_config(config_path)
    except Exception as e:
        logger.error(f"Failed to load config from {config_path}: {e}")
        yield
        return

    _shutdown_event.clear()
    default_model_name = app_config.katago.default_model
    _models_by_name = {m.name: m for m in app_config.katago.models}
    katago_cfg = app_config.katago

    # Everything after resource creation is wrapped in try/finally so cleanup runs on ANY
    # exit — normal shutdown, an exception, OR a cancellation injected during startup
    # (before yield) or at the yield point. Code after a bare `yield` would be skipped on
    # such abnormal exits, which is exactly how a download worker could be orphaned.
    try:
        # Dedicated joinable pool for downloads (2 slots/model: main + human).
        _download_executor = ThreadPoolExecutor(
            max_workers=max(2, len(katago_cfg.models) * 2), thread_name_prefix="model-download"
        )

        # 1) Construct ALL wrappers up front (process is None until started). Every
        #    configured name is present in `wrappers` immediately; /analyze returns 503
        #    (not 400) for a configured-but-not-yet-ready model, 400 only for unknown names.
        for m in katago_cfg.models:
            wrappers[m.name] = _new_wrapper(m)

        # 2) Bring up the DEFAULT model SYNCHRONOUSLY → ready at yield, independent of any
        #    secondary. (Downloading its own humanv0 here also means the shared artifact is
        #    already present+verified before any secondary bring-up runs.)
        await _supervise_bring_up(default_model_name)

        # 3) Bring up every OTHER model in the BACKGROUND so they cannot delay serving.
        _bringup_tasks = [
            asyncio.create_task(_supervise_bring_up(m.name))
            for m in katago_cfg.models
            if m.name != default_model_name
        ]

        yield

    finally:
        # (a) signal downloads to abort cooperatively; (b) cancel/await the asyncio bring-up
        # tasks (handles tasks blocked on asyncio, e.g. an artifact lock); (c) JOIN the
        # download pool so no worker thread outlives lifespan (cancelling a run_in_executor
        # awaiter does NOT stop its thread — only shutdown(wait=True) guarantees the worker
        # exited and cleaned its <dest>.tmp). Each await is guarded so a cancellation during
        # cleanup cannot skip the executor join; the join falls back to a synchronous call.
        _shutdown_event.set()
        for t in _bringup_tasks:
            t.cancel()
        try:
            if _bringup_tasks:
                await asyncio.gather(*_bringup_tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass
        _bringup_tasks = []
        if _download_executor is not None:
            ex = _download_executor
            _download_executor = None
            try:
                await asyncio.get_running_loop().run_in_executor(None, ex.shutdown, True)
            except asyncio.CancelledError:
                ex.shutdown(wait=True)  # last-resort synchronous join so no worker is orphaned
        for name, wrapper in list(wrappers.items()):
            try:
                await wrapper.stop()
                logger.info("Model '%s' stopped", name)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("Error stopping model '%s': %s", name, e)
        wrappers.clear()


def _new_wrapper(m: "NamedModelConfig") -> KataGoWrapper:
    human_path = m.human_model.path if m.human_model else None
    kc = app_config.katago
    return KataGoWrapper(
        kc.path,
        kc.config_path,
        m.path,
        human_model_path=human_path,
        additional_args=list(kc.additional_args) + list(m.additional_args),
        ld_library_paths=kc.ld_library_paths,
    )


def _artifact_lock(path: str) -> "asyncio.Lock":
    lock = _artifact_locks.get(path)
    if lock is None:
        lock = asyncio.Lock()
        _artifact_locks[path] = lock
    return lock


async def _ensure_artifact(model: "ModelConfig", label: str) -> None:
    """Ensure one artifact, serialized per destination path so concurrent bring-ups that
    share an artifact (e.g. the same humanv0) never download into the same temp file at
    once."""
    async with _artifact_lock(model.path):
        await _ensure_single_model(model, label)


async def _supervise_bring_up(name: str) -> None:
    """Guarded, dedup'd bring-up of one model. Only one attempt per model runs at a time
    (`_bringup_inflight`). If the model is already healthy, it is a no-op. Otherwise it
    installs a FRESH wrapper and (re)brings it up — so a model that failed its first
    bring-up, or whose subprocess later died, can recover WITHOUT restarting the app
    (KataGoWrapper.start() early-returns on a stale process handle, so recovery needs a
    fresh wrapper, not a re-start of the old one)."""
    if name in _bringup_inflight:
        return
    w = wrappers.get(name)
    if w is not None and w.process is not None and w.process.returncode is None:
        return  # already healthy — do not clobber a running model
    _bringup_inflight.add(name)
    try:
        m = _models_by_name[name]
        wrappers[name] = _new_wrapper(m)  # fresh wrapper for a clean (re)start
        await _bring_up_model(m, wrappers[name])
    finally:
        _bringup_inflight.discard(name)


def _schedule_bring_up(name: str) -> None:
    """Fire-and-forget guarded bring-up used by /analyze to LAZILY heal a not-ready model
    (transient download/spawn failure). No-op if one is already in flight; the current
    request still gets 503, but a subsequent request can find the model healed."""
    if name in _bringup_inflight or name not in _models_by_name:
        return
    # Prune finished tasks so this list stays bounded over the server's lifetime, and keep
    # a live reference to the new task (so it is not GC'd mid-flight).
    _bringup_tasks[:] = [t for t in _bringup_tasks if not t.done()]
    _bringup_tasks.append(asyncio.create_task(_supervise_bring_up(name)))


async def _bring_up_model(m: "NamedModelConfig", wrapper: KataGoWrapper) -> None:
    """Ensure artifacts + start ONE wrapper under its own exception boundary. Never raises
    (except CancelledError); on failure the wrapper simply has no live process, which
    /health reports as not-running and /analyze answers 503 for."""
    logger.info("Bringing up model '%s': main=%s", m.name, m.path)
    try:
        await _ensure_artifact(m, f"Main model [{m.name}]")
        if m.human_model:
            await _ensure_artifact(m.human_model, f"Human model [{m.name}]")
        await wrapper.start()
        logger.info("Model '%s' started", m.name)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("Failed to bring up model '%s': %s", m.name, e)
```

Import `NamedModelConfig` and `ModelConfig` for the annotations (extend the existing config import):

```python
from .config import (
    AppConfig,
    ModelConfig,
    NamedModelConfig,
    get_config_path_for_mode,
    get_default_config_path,
    load_config,
)
```

Add a routing helper just above `@app.post("/analyze")`:

```python
def _pop_route_model(query: dict):
    """Extract & REMOVE the routing selector `overrideSettings.model` so it never
    reaches the katago subprocess (which rejects unknown override keys). Returns
    `_MODEL_KEY_ABSENT` when the key was not present (→ caller uses default), otherwise
    the raw popped value (which the caller MUST validate — it may be null/empty/wrong)."""
    override = query.get("overrideSettings")
    if isinstance(override, dict) and "model" in override:
        return override.pop("model")
    return _MODEL_KEY_ABSENT
```

Replace `/analyze` — note the strict selector validation: an absent key uses the default, but any *present* value that is not a non-empty string, or that names no configured model, is a 400 (never a silent fallback):

```python
@app.post("/analyze")
async def analyze(request: MoveRequest):
    if not wrappers:
        raise HTTPException(status_code=503, detail="KataGo engine not initialized")

    query = request.model_dump(exclude_none=True)
    requested = _pop_route_model(query)
    if requested is _MODEL_KEY_ABSENT:
        name = default_model_name
    else:
        if not isinstance(requested, str) or not requested.strip():
            raise HTTPException(
                status_code=400,
                detail=f"invalid model selector {requested!r}; available: {sorted(wrappers)}",
            )
        name = requested

    wrapper = wrappers.get(name)
    if wrapper is None:
        # Genuinely unknown model name (never configured) → 400.
        raise HTTPException(
            status_code=400, detail=f"unknown model '{name}'; available: {sorted(wrappers)}"
        )
    if not wrapper.process or wrapper.process.returncode is not None:
        # Configured but not (yet) ready: still downloading/starting, or its process died.
        # Lazily (re)trigger a guarded bring-up so a transient failure can heal without an
        # app restart, and answer 503 for THIS request (a retry may find it healed).
        _schedule_bring_up(name)
        raise HTTPException(status_code=503, detail=f"model '{name}' is not ready")

    if request.gameId or request.userId:
        logger.info(f"Analysis {request.id} model={name} game={request.gameId} user={request.userId}")

    try:
        return await wrapper.query(query)
    except Exception as e:
        logger.error(f"Analysis failed (id={request.id}, model={name}): {e}")
        if wrapper.process and wrapper.process.returncode is not None:
            raise HTTPException(status_code=503, detail="KataGo engine process died")
        raise HTTPException(status_code=500, detail=str(e))
```

Replace `/health` — build the COMPLETE per-model report first (never early-return mid-loop), then apply the readiness policy: 503 iff the DEFAULT model is unavailable (but STILL return the full report so operators see which models survive); otherwise 200, `ok` if all run else `degraded`:

```python
@app.get("/health")
async def health():
    if not wrappers:
        raise HTTPException(status_code=503, detail="Wrapper not initialized")

    path_by_name = {}
    if app_config:
        for m in app_config.katago.models:
            path_by_name[m.name] = m.path

    models = {}
    for name, wrapper in wrappers.items():
        proc = wrapper.process
        running = bool(proc) and proc.returncode is None
        models[name] = {
            "pid": proc.pid if proc else None,
            "running": running,
            "returncode": proc.returncode if proc else None,
            "has_human_model": wrapper.has_human_model,
            "model": path_by_name.get(name),
        }

    all_ok = all(m["running"] for m in models.values())
    default_ok = default_model_name in models and models[default_model_name]["running"]
    body = {
        "status": "ok" if all_ok else "degraded",
        "default_model": default_model_name,
        "models": models,
    }
    if not default_ok:
        # Default model down → fail the health check so load balancers pull this
        # instance, but keep the full per-model report in the body for operators.
        return JSONResponse(status_code=503, content={**body, "status": "unavailable"})
    return body
```

`_ensure_models_available` is no longer called (bring-up is per-model inside `_bring_up_model`); **delete** the old `_ensure_models_available` function (current lines 144-147).

Make `_download_model` **cooperatively cancellable** so a shutdown that sets `_shutdown_event` aborts a blocked/retrying download instead of orphaning the executor thread. Change its signature and add three checks (top of each attempt, inside the chunk loop, and replacing the blocking `time.sleep` backoff with an interruptible wait):

```python
def _download_model(url: str, dest_path: str, expected_sha: Optional[str], retries: int = 10) -> None:
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    tmp_path = f"{dest_path}.tmp"

    last_error = None
    for attempt in range(retries):
        if _shutdown_event.is_set():                      # (1) abort before starting an attempt
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise RuntimeError("download aborted: server shutting down")
        hasher = hashlib.sha256()
        try:
            if attempt > 0:
                logger.info(f"Downloading {url} (Attempt {attempt + 1}/{retries})")
            req = urllib.request.Request(url, headers={"User-Agent": "KataGo/1.0"})
            with urllib.request.urlopen(req, timeout=60) as response, open(tmp_path, "wb") as handle:
                total_bytes = _get_content_length(response)
                bytes_read = 0
                last_update = 0.0
                while True:
                    if _shutdown_event.is_set():          # (2) abort mid-stream
                        raise RuntimeError("download aborted: server shutting down")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    hasher.update(chunk)
                    bytes_read += len(chunk)
                    last_update = _print_progress(bytes_read, total_bytes, last_update)
                _print_progress(bytes_read, total_bytes, last_update, force=True)
                sys.stdout.write("\n")
                sys.stdout.flush()

            if expected_sha:
                actual_sha = hasher.hexdigest().lower()
                if actual_sha != expected_sha:
                    raise ValueError(
                        "Model checksum mismatch: expected %s, got %s" % (expected_sha, actual_sha)
                    )
                logger.info("Model checksum verified after download.")

            os.replace(tmp_path, dest_path)
            return  # Success

        except Exception as e:
            last_error = e
            logger.warning(f"Download attempt {attempt + 1} failed: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            if _shutdown_event.is_set():                  # (3a) do not retry during shutdown
                raise
            if attempt < retries - 1:
                sleep_time = 2 ** attempt
                logger.info(f"Retrying in {sleep_time} seconds...")
                if _shutdown_event.wait(sleep_time):      # (3b) interruptible backoff
                    raise RuntimeError("download aborted: server shutting down")

    raise last_error
```

In `_ensure_single_model`, route the download onto the **joinable** pool so shutdown can wait for it — change the one executor line from the default executor to `_download_executor`:

```python
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_download_executor, _download_model, model.url, model.path, expected_sha)
```

(When `_download_executor` is `None` — e.g. a direct unit-test call outside lifespan — `run_in_executor(None, ...)` falls back to the default executor, so this is safe everywhere.) No other download helper needs changes; `_shutdown_event` is a module global the worker reads directly.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=python pytest tests/test_realtime_api.py -v`
Expected: PASS (updated legacy tests + new routing/malformed-selector/health-readiness/legacy-lifespan tests).

- [ ] **Step 6: Run the full realtime_api + config test set for regressions**

Run: `PYTHONPATH=python pytest tests/test_realtime_api.py tests/test_realtime_api_full.py tests/test_realtime_api_multitenancy.py tests/test_realtime_api_bounds.py tests/test_human_model.py tests/test_config.py -v`
Expected: PASS. **All four files that patched the old `katago_wrapper` global (`test_realtime_api.py`, `test_human_model.py`, `test_realtime_api_bounds.py`, `test_realtime_api_multitenancy.py`) must be converted (Steps 2 + 2b) before this passes.** If `test_realtime_api_full.py` also references `katago_wrapper` (grep it — current tree does not), apply the same registry conversion.

- [ ] **Step 7: Commit**

Include EVERY converted test file and the dev-dep bump so the suite is green from a clean checkout:

```bash
git add python/realtime_api/main.py \
        tests/test_realtime_api.py tests/test_human_model.py \
        tests/test_realtime_api_bounds.py tests/test_realtime_api_multitenancy.py \
        requirements-api.txt
git commit -m "feat(realtime_api): per-model wrapper registry + overrideSettings.model routing + multi-model /health"
```

---

### Task 3: Server `config.yaml` → b28 + b18, and end-to-end smoke

**Files:**
- Modify: `config.yaml`

**Interfaces:**
- Consumes: the `models[]` schema (Task 1) and routing (Task 2).

- [ ] **Step 1: Rewrite `config.yaml` to declare two models**

Replace the whole `katago:` mapping's `model:`/`human_model:` block with `models:` + `default_model:` (keep `path`, `config_path`, `additional_args`, `ld_library_paths`, and the `api:` block as they are):

```yaml
katago:
  path: ./cpp/katago
  config_path: ./cpp/configs/server_analysis.cfg
  models:
    - name: b28
      path: ./models/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz
      url: https://media.katagotraining.org/uploaded/networks/models/kata1/kata1-b28c512nbt-adam-s11165M-d5387M.bin.gz
      auto_download: true
      sha256: 798da8fe3e9819f09535240b1bc29cb3047a4fa981433c56c491e57007a3d3f0
      human_model:
        path: ./models/b18c384nbt-humanv0.bin.gz
        url: https://github.com/lightvector/KataGo/releases/download/v1.15.0/b18c384nbt-humanv0.bin.gz
        auto_download: true
        sha256: 637746e44f0efe00ad1245a50aa9bbf0716efe364c43965ead97bd6835d84ab5
    - name: b18
      path: ./models/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz
      url: https://media.katagotraining.org/uploaded/networks/models/kata1/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz
      auto_download: true
      sha256: 9d7a6afed8ff5b74894727e156f04f0cd36060a24824892008fbb6e0cba51f1d
      human_model:
        path: ./models/b18c384nbt-humanv0.bin.gz
        url: https://github.com/lightvector/KataGo/releases/download/v1.15.0/b18c384nbt-humanv0.bin.gz
        auto_download: true
        sha256: 637746e44f0efe00ad1245a50aa9bbf0716efe364c43965ead97bd6835d84ab5
  default_model: b28
  additional_args: []
  ld_library_paths:
    - ./libs/TensorRT-8.6/lib
    - /usr/local/cuda/lib64

api:
  host: 0.0.0.0
  port: 8000
  reload: false
```

- [ ] **Step 2: Assert the real config loads (schema smoke, no engine)**

Run:
```bash
PYTHONPATH=python python3 -c "from realtime_api.config import load_config; c=load_config('config.yaml'); print(c.katago.default_model, [m.name for m in c.katago.models])"
```
Expected: `b28 ['b28', 'b18']`

- [ ] **Step 3: Provide the Metal binary to the worktree, then launch**

`cpp/katago` is git-ignored (not in the worktree). Symlink it from the main checkout (self-contained Metal binary — verified):
```bash
ln -sfn /Users/fan/Repositories/KataGo/cpp/katago /Users/fan/Repositories/KataGo-add-b18-model/cpp/katago
```
Launch (auto-downloads b28/b18/humanv0 into `./models/` on first run; two subprocesses start):
```bash
PYTHONPATH=python python3 -m realtime_api.main --mode server
```
Expected log: two `Model 'b28' started` / `Model 'b18' started` lines.

- [ ] **Step 4: Smoke the routing over HTTP**

In another shell:
```bash
curl -s localhost:8000/health | python3 -m json.tool
```
Expected: `default_model": "b28"` and a `models` object with both `b28` and `b18` running.

```bash
curl -s localhost:8000/analyze -H 'content-type: application/json' \
  -d '{"id":"t","moves":[["B","Q4"]],"maxVisits":2,"overrideSettings":{"model":"b18"}}' | python3 -c "import sys,json;d=json.load(sys.stdin);print('moveInfos:',len(d.get('moveInfos',[])),'err:',d.get('error'))"
```
Expected: a non-empty `moveInfos`, no error (routed to the b18 subprocess). Stop the server (Ctrl-C) when done.

- [ ] **Step 4b: Functional concurrency smoke (both nets under simultaneous load)**

A single two-visit request cannot expose concurrent behavior. Fire a small simultaneous burst at both nets and assert none returns 5xx (this is a *functional* check that two live subprocesses can serve concurrently — NOT a calibrated capacity gate):

```bash
PYTHONPATH=python python3 - <<'PY'
import asyncio, httpx
async def one(client, model, i):
    ov = {"model": model} if model else {}
    r = await client.post("http://localhost:8000/analyze", json={
        "id": f"burst-{model}-{i}",              # UNIQUE id per request (pending_requests is id-keyed)
        "moves": [["B","Q4"]], "maxVisits": 2, "overrideSettings": ov})
    body = r.json() if r.headers.get("content-type","").startswith("application/json") else {}
    return {"model": model, "i": i, "status": r.status_code,
            "moveInfos": len(body.get("moveInfos", [])), "error": body.get("error")}
async def main():
    async with httpx.AsyncClient(timeout=120) as c:
        reqs = [one(c, m, i) for m in ["b28","b18"] for i in range(4)]
        res = await asyncio.gather(*reqs, return_exceptions=True)
    print("results:", res)
    excs = [r for r in res if isinstance(r, Exception)]
    assert not excs, f"requests raised: {excs}"
    non200 = [r for r in res if r["status"] != 200]
    assert not non200, f"expected all 200, got: {non200}"
    empty = [r for r in res if r["moveInfos"] == 0 or r["error"]]
    assert not empty, f"got empty/error responses: {empty}"
    print("OK: 8/8 concurrent requests returned 200 with non-empty moveInfos")
asyncio.run(main())
PY
```
Expected: `OK: 8/8 ...`. Every request has a UNIQUE id (so id-keyed `pending_requests` futures never collide), every status is exactly `200`, and every response has non-empty `moveInfos`. (If this OOMs or collapses on the target GPU, that is the signal to use per-model device assignment — see the scope note.)

> **Scope note (deliberate, not an omission):** the smokes above validate *functional
> routing, startup isolation, and basic concurrent serving* only. They intentionally do
> NOT set calibrated capacity thresholds for the doubled production envelope (two
> subprocesses share `server_analysis.cfg`: 8 analysis × 8 search threads,
> `nnMaxBatchSize=64`, same default GPU → ~2× VRAM/compute). Calibrated VRAM/latency
> acceptance thresholds and b18-vs-b28 strength calibration are explicitly out of scope
> per prd.md §8–§9 and tracked as follow-ups. When capacity must be controlled, the
> **real** per-model `additional_args` lever (Task 1's `NamedModelConfig.additional_args`,
> e.g. `["-override-config", "cudaDeviceToUseThread0=1"]` on b18) splits the two nets
> across devices — a config-only change validated by Task 1's
> `test_per_model_additional_args_default_empty_and_parsed`.

---

### Task 4: Docs — routing contract

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Add a routing section to `README.md`**

Find the realtime_api API section (grep anchor: `PYTHONPATH=python python3 -m realtime_api.main`). Immediately after the `--mode` modes description, insert:

```markdown
#### Model routing (server mode)

`config.yaml` (server mode) hosts **two models** — `b28` (default, strongest; top-tier play + review) and `b18` (compute-light; high-dan/5D+ play). Each runs as its own KataGo subprocess.

Select the model per request with `overrideSettings.model`:

- `{"overrideSettings": {"model": "b18"}}` → b18 subprocess
- `{"overrideSettings": {"model": "b28"}}` (or omit) → default (b28)
- `overrideSettings.humanSLProfile` combines with routing: the selected subprocess uses its attached human net. **Existing humanSL traffic carries no `model` field and therefore keeps landing on the default (b28) wrapper — byte-identical to today.** Sending `humanSLProfile` together with `model:"b18"` is a *new* capability; because the engine can blend human policy with the main net's search, b18 humanSL play may differ from b28 and is not calibrated here.

A present-but-invalid model selector (`null`, empty/whitespace, non-string, or an unknown name) returns **HTTP 400** — the request is never silently served by a different net. `GET /health` reports every model's status under `models` and returns **503 if the default model is down** (with the full report still in the body). The legacy single-`model:` config form (used by `config.sbc.yaml`) is still accepted and behaves exactly as before.
```

- [ ] **Step 2: Add a one-line note to `AGENTS.md`**

Find the realtime_api bullet (grep anchor: `real-time API lives in`). Add a sibling bullet:

```markdown
- The realtime API can host multiple models (`config.yaml` → `katago.models[]` + `default_model`); requests pick one via `overrideSettings.model` (default = `default_model`). Legacy single-`model:` configs still work.
```

- [ ] **Step 3: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs(realtime_api): document overrideSettings.model routing + multi-model /health"
```

---

## Self-Review

**1. Spec coverage** (against `prd.md`):
- §4.1 config schema → Task 1. §4.2 server config → Task 3. §4.3 registry → Task 2 (lifespan). §4.4 routing + strip → Task 2 (`_pop_route_model`, tests). §4.5 health → Task 2. §4.6 worktree symlink → Task 3 Step 3. §5 routing contract → Task 2 tests + Task 4 docs. §6 back-compat → Task 1 (`test_legacy_single_model_config_still_loads`) + Task 2 (default route). §7 tests → Tasks 1–2. Non-goals (kiosk/KaTrain/new-mode) untouched. ✓ no gaps.

**2. Placeholder scan:** every code step has complete code; commands have expected output; no TBD/TODO. ✓

**3. Type consistency:** `NamedModelConfig(name, human_model, additional_args)`, `KataGoConfig.models`/`default_model`, globals `wrappers`/`default_model_name`/`_models_by_name`/`_bringup_tasks`/`_bringup_inflight`/`_artifact_locks`/`_download_executor`/`_shutdown_event`/`_MODEL_KEY_ABSENT`, helpers `_new_wrapper(m)->KataGoWrapper`, `_supervise_bring_up(name)->None`, `_schedule_bring_up(name)`, `_bring_up_model(m, wrapper)->None`, `_ensure_artifact(model, label)`, `_artifact_lock(path)`, `_pop_route_model(query)-> value|_MODEL_KEY_ABSENT`, `/health` shape `{status, default_model, models{name:{pid,running,returncode,has_human_model,model}}}` — used identically in the schema, main.py, and every test. ✓

**4. Adversarial-review resolution** (Codex pass, 2026-07-20):
- *humanSL not independent of main net (high)* → removed the independence claim; docs + Global Constraints now state byte-identical humanSL is guaranteed only on the default (b28) wrapper (where all current humanSL traffic lands); b18+humanSL is new/uncalibrated. (Task 4, Global Constraints)
- *secondary download blocks default startup (high)* → lifespan brings each model up under its own exception boundary (default synchronous, secondaries as background tasks — see round 2 below for the final, non-blocking design); a broken/slow secondary can neither block nor abort the default. (Task 2 Step 4)
- *health hides per-model failure / 200 for failed engine (high)* → `/health` builds the full per-model report first, then 503 iff the default model is down (report still in body), else 200 ok/degraded. Tests cover default-down-503, non-default-degraded-200, failed-start-503. (Task 2 Steps 1, 4)
- *silent default_model / mixed schema (medium)* → validator now requires explicit `default_model` when `models[]` is given and rejects configs supplying both `models[]` and legacy `model`. Tests added. (Task 1)
- *falsy routing value silently falls back (medium)* → `_pop_route_model` returns a sentinel for key-absence; any present-but-invalid value (null/empty/whitespace/non-string/unknown) → 400. Parametrized tests added. (Task 2 Steps 1, 4)
- *regression suite still patches removed global (medium)* → Step 2b converts all four affected files (`test_realtime_api.py`, `test_human_model.py`, `test_realtime_api_bounds.py`, `test_realtime_api_multitenancy.py`); Step 2c adds a legacy single-model lifespan test; Steps 6–7 run and commit them all. (Task 2)
- *smoke doesn't validate doubled resource envelope (medium)* → consciously deferred per prd.md §8–§9 (calibration/capacity out of scope); documented as a deliberate scope note with the `additional_args` device-split lever called out. (Task 3 Step 4)

**4b. Adversarial-review resolution — round 2** (Codex re-pass, 2026-07-20):
- *gather still blocks default on slowest secondary (high)* → redesigned lifespan: all wrappers constructed up front, DEFAULT brought up synchronously (ready at `yield`), every SECONDARY brought up in a background `asyncio` task; new `test_default_serves_while_secondary_bringup_blocked` proves the app serves b28 (200) and answers 503 for a still-blocked b18 while its bring-up hangs. (Task 2 Steps 2d, 4)
- *concurrent bring-up races on shared humanv0 artifact (high)* → default fully prepared before any secondary starts, plus a per-destination `_artifact_lock` serializes shared-artifact downloads; `test_artifact_lock_is_per_destination` guards the dedup. (Task 2 Steps 2e, 4)
- *resource envelope + non-existent additional_args lever (high)* → the lever is now REAL: `NamedModelConfig.additional_args` is appended per-model in wrapper construction (`test_per_model_additional_args_default_empty_and_parsed`); added a functional concurrency smoke (Task 3 Step 4b); calibrated capacity thresholds remain a PRD-scoped deferral.
- *after-validator can't detect key presence / misses models[]+legacy human_model (medium)* → schema-form detection moved to a `mode="before"` validator over the raw mapping; rejects `models`+legacy `model`/`human_model` and explicit empty `models: []`; tests `test_mixed_legacy_human_model_and_models_rejected`, `test_empty_models_list_rejected` added. (Task 1)

**4c. Adversarial-review resolution — round 3** (Codex re-pass, 2026-07-20; all 3 findings were NEW defects introduced by round-2 additions):
- *cancelling bring-up tasks doesn't stop executor-backed downloads (high)* → `_download_model` is now cooperatively cancellable via the module `threading.Event` `_shutdown_event` (checked before each attempt, mid-stream, and as an interruptible backoff wait); shutdown SETS the event before cancelling tasks so the worker aborts and cleans its `.tmp` rather than orphaning. Test `test_download_aborts_on_shutdown_event`. **Round 4 hardening:** downloads run on a dedicated joinable `_download_executor`; shutdown JOINs it with `executor.shutdown(wait=True)` so a worker blocked mid-`read()` (bounded by the socket timeout) is guaranteed to terminate and clean its `<dest>.tmp` before lifespan returns — no orphaned thread can race a subsequent lifespan on the same temp path. Test `test_shutdown_joins_download_worker_and_cleans_tmp`. **Round 5 hardening:** all work after resource creation (executor, wrapper construction, default bring-up, secondary scheduling, `yield`) is wrapped in `try/finally`, so cleanup — event signal, task cancel/await, executor JOIN (with a synchronous fallback if the cleanup await is itself cancelled), wrapper stop, registry clear — runs on ANY exit, including a cancellation injected during startup or at the yield. Test `test_lifespan_cleanup_runs_on_cancellation` drives the real lifespan and throws `CancelledError` at the yield, asserting the join ran and the registry cleared. (Task 2 Steps 2h, 2i, 4)
- *transient bring-up failure leaves model permanently 503 (medium)* → introduced the guarded, dedup'd `_supervise_bring_up(name)` (installs a FRESH wrapper so a failed/dead model recovers without an app restart) + `_schedule_bring_up(name)` lazy heal triggered from `/analyze`'s 503 path. Test `test_model_recovers_from_transient_bringup_failure`. (Task 2 Steps 2f, 4)
- *concurrency smoke reuses request IDs → orphaned responses (medium)* → smoke now uses a UNIQUE id per request (id-keyed `pending_requests` never collide), collects exceptions, and asserts every status is exactly 200 with non-empty `moveInfos`. (Task 3 Step 4b)

**Known follow-ups (out of scope, tracked in prd.md §8):** KaTrain sets `overrideSettings.model`; RK3562 高段位 cap-vs-cloud decision; b18-capable SBC config; b18-vs-b28 calibration; production capacity/GPU-envelope validation for 2 concurrent subprocesses.
