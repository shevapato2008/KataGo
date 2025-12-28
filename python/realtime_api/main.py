import asyncio
import hashlib
import logging
import os
import sys
import time
import uuid
import urllib.request
from contextlib import asynccontextmanager
from typing import List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import AppConfig, get_default_config_path, load_config
from .katago_wrapper import KataGoWrapper

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("realtime_api")

katago_wrapper: Optional[KataGoWrapper] = None
app_config: Optional[AppConfig] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global katago_wrapper
    global app_config

    if katago_wrapper is not None:
        yield
        return

    config_path = os.getenv("KATAGO_CONFIG_FILE") or get_default_config_path()
    try:
        app_config = load_config(config_path)
    except Exception as e:
        logger.error(f"Failed to load config from {config_path}: {e}")
        yield
        return
    
    # In a real deployment, we might want to fail fast if model is missing.
    # For now, we initialize and let the wrapper handle startup errors or wait for first request.
    logger.info(
        "Initializing KataGo Wrapper with: Bin=%s, Config=%s, Model=%s",
        app_config.katago.path,
        app_config.katago.config_path,
        app_config.katago.model.path,
    )

    await _ensure_model_available(app_config)
    katago_wrapper = KataGoWrapper(
        app_config.katago.path,
        app_config.katago.config_path,
        app_config.katago.model.path,
        additional_args=app_config.katago.additional_args,
        ld_library_paths=app_config.katago.ld_library_paths,
    )
    try:
        # We try to start it. If it fails (e.g. no model), we log error but keep app running
        # so /health can report failure or we can fix it.
        await katago_wrapper.start()
        logger.info("KataGo wrapper started")
    except Exception as e:
        logger.error(f"Failed to start KataGo wrapper during startup: {e}")
    
    yield
    
    if katago_wrapper:
        await katago_wrapper.stop()
        logger.info("KataGo wrapper stopped")

app = FastAPI(lifespan=lifespan)

class MoveRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    moves: List[Tuple[str, str]] = [] 
    initialStones: List[Tuple[str, str]] = []
    rules: str = "Chinese"
    komi: float = 7.5
    boardXSize: int = 19
    boardYSize: int = 19
    includePolicy: bool = True
    maxVisits: Optional[int] = None
    priority: int = 0

@app.post("/analyze")
async def analyze(request: MoveRequest):
    if not katago_wrapper:
        raise HTTPException(status_code=503, detail="KataGo engine not initialized")
    
    query = request.model_dump(exclude_none=True)
    
    try:
        result = await katago_wrapper.query(query)
        return result
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        # Check if process is dead
        if katago_wrapper.process and katago_wrapper.process.returncode is not None:
             raise HTTPException(status_code=503, detail="KataGo engine process died")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    if not katago_wrapper:
         raise HTTPException(status_code=503, detail="Wrapper not initialized")
    
    if not katago_wrapper.process:
         # It might have failed to start or hasn't started yet
         raise HTTPException(status_code=503, detail="KataGo process not running")
         
    if katago_wrapper.process.returncode is not None:
         raise HTTPException(status_code=503, detail=f"KataGo process exited with code {katago_wrapper.process.returncode}")
         
    return {"status": "ok", "pid": katago_wrapper.process.pid}


async def _ensure_model_available(config: AppConfig) -> None:
    model = config.katago.model
    expected_sha = _normalize_sha256(model.sha256)
    if expected_sha:
        logger.info("Expected model SHA256: %s", expected_sha)
    if os.path.isfile(model.path):
        if expected_sha:
            if _verify_model_checksum(model.path, expected_sha):
                return
            if not model.auto_download:
                logger.error("Model checksum mismatch for %s", model.path)
                return
            logger.warning("Model checksum mismatch, re-downloading: %s", model.path)
            os.remove(model.path)
        else:
            return
    if not model.auto_download:
        return
    if not model.url:
        logger.error("Model auto-download enabled but no model URL configured.")
        return

    logger.info("Downloading model from %s to %s", model.url, model.path)
    try:
        await asyncio.to_thread(_download_model, model.url, model.path, expected_sha)
        logger.info("Model download completed.")
    except Exception as e:
        logger.error("Failed to download model: %s", e)


def _download_model(url: str, dest_path: str, expected_sha: Optional[str]) -> None:
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    tmp_path = f"{dest_path}.tmp"
    hasher = hashlib.sha256()
    try:
        with urllib.request.urlopen(url) as response, open(tmp_path, "wb") as handle:
            total_bytes = _get_content_length(response)
            bytes_read = 0
            last_update = 0.0
            while True:
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
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


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
    import uvicorn

    config_path = os.getenv("KATAGO_CONFIG_FILE") or get_default_config_path()
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
