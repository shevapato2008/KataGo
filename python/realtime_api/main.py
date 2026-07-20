import asyncio
import hashlib
import logging
import os
import sys
import threading
import time
import uuid
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import (
    AppConfig,
    ModelConfig,
    NamedModelConfig,
    get_config_path_for_mode,
    get_default_config_path,
    load_config,
)
from .katago_wrapper import KataGoWrapper

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("realtime_api")

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


app = FastAPI(lifespan=lifespan)

class RegionBounds(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int

class MoveRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    gameId: Optional[str] = None
    userId: Optional[str] = None
    moves: List[Tuple[str, str]] = []
    initialStones: List[Tuple[str, str]] = []
    rules: str = "Chinese"
    komi: float = 7.5
    boardXSize: int = 19
    boardYSize: int = 19
    analyzeTurns: Optional[List[int]] = None
    regionBounds: Optional[RegionBounds] = None
    includePolicy: bool = True
    includeOwnership: bool = False
    maxVisits: Optional[int] = None
    priority: int = 0
    overrideSettings: Optional[dict] = None

def _pop_route_model(query: dict):
    """Extract & REMOVE the routing selector `overrideSettings.model` so it never
    reaches the katago subprocess (which rejects unknown override keys). Returns
    `_MODEL_KEY_ABSENT` when the key was not present (→ caller uses default), otherwise
    the raw popped value (which the caller MUST validate — it may be null/empty/wrong)."""
    override = query.get("overrideSettings")
    if isinstance(override, dict) and "model" in override:
        return override.pop("model")
    return _MODEL_KEY_ABSENT


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

async def _ensure_single_model(model: "ModelConfig", label: str) -> None:
    expected_sha = _normalize_sha256(model.sha256)
    if expected_sha:
        logger.info("%s expected SHA256: %s", label, expected_sha)
    if os.path.isfile(model.path):
        if expected_sha:
            if _verify_model_checksum(model.path, expected_sha):
                return
            if not model.auto_download:
                logger.error("%s checksum mismatch for %s", label, model.path)
                return
            logger.warning("%s checksum mismatch, re-downloading: %s", label, model.path)
            os.remove(model.path)
        else:
            return
    if not model.auto_download:
        return
    if not model.url:
        logger.error("%s auto-download enabled but no URL configured.", label)
        return

    logger.info("Downloading %s from %s to %s", label, model.url, model.path)
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_download_executor, _download_model, model.url, model.path, expected_sha)
        logger.info("%s download completed.", label)
    except Exception as e:
        logger.error("Failed to download %s: %s", label, e)

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

            # Some hosts (e.g. Google Cloud Storage) block Python-urllib User-Agent
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
                sleep_time = 2 ** attempt  # Exponential backoff
                logger.info(f"Retrying in {sleep_time} seconds...")
                if _shutdown_event.wait(sleep_time):      # (3b) interruptible backoff
                    raise RuntimeError("download aborted: server shutting down")

    # If we get here, all retries failed
    raise last_error

def _verify_model_checksum(path: str, expected_sha: str) -> bool:
    logger.info("Verifying model checksum for %s", path)
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    actual_sha = hasher.hexdigest().lower()
    if actual_sha != expected_sha:
        logger.warning("Model checksum mismatch: expected %s, got %s", expected_sha, actual_sha)
        return False
    logger.info("Model checksum verified for %s", path)
    return True

def _normalize_sha256(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.strip().lower()

def _get_content_length(response: urllib.request.addinfourl) -> Optional[int]:
    header = response.getheader("Content-Length")
    if not header:
        return None
    try:
        return int(header)
    except ValueError:
        return None

def _print_progress(
    bytes_read: int, total_bytes: Optional[int], last_update: float, force: bool = False
) -> float:
    now = time.monotonic()
    if not force and now - last_update < 0.2:
        return last_update

    if total_bytes:
        ratio = min(bytes_read / total_bytes, 1.0)
        bar_width = 30
        filled = int(bar_width * ratio)
        bar = "=" * filled + "-" * (bar_width - filled)
        percent = ratio * 100
        sys.stdout.write(f"\rDownloading model [{bar}] {percent:5.1f}%")
    else:
        mib = bytes_read / (1024 * 1024)
        sys.stdout.write(f"\rDownloading model {mib:6.1f} MiB")
    sys.stdout.flush()
    return now

if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="KataGo Real-Time API")
    parser.add_argument(
        "--mode",
        choices=["server", "sbc"],
        default="server",
        help="Launch mode: 'server' (default, full model) or 'sbc' (lightweight for SBC)",
    )
    args = parser.parse_args()

    # Resolve config: KATAGO_CONFIG_FILE env → --mode flag → default (server)
    env_config = os.getenv("KATAGO_CONFIG_FILE")
    if env_config:
        config_path = env_config
        logger.info("Using config from KATAGO_CONFIG_FILE: %s", config_path)
    else:
        config_path = get_config_path_for_mode(args.mode)
        logger.info("Launching in '%s' mode with config: %s", args.mode, config_path)

    # Expose to lifespan via env so the forked uvicorn workers pick it up
    os.environ["KATAGO_CONFIG_FILE"] = config_path

    try:
        runtime_config = load_config(config_path)
    except Exception as e:
        logger.error("Failed to load config from %s: %s", config_path, e)
        raise SystemExit(1)

    # We use the import string "realtime_api.main:app" so that reload works
    uvicorn.run(
        "realtime_api.main:app",
        host=runtime_config.api.host,
        port=runtime_config.api.port,
        reload=runtime_config.api.reload,
    )
