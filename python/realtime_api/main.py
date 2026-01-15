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

    await _ensure_models_available(app_config)
    
    human_model_path = None
    if app_config.katago.human_model:
        human_model_path = app_config.katago.human_model.path

    katago_wrapper = KataGoWrapper(
        app_config.katago.path,
        app_config.katago.config_path,
        app_config.katago.model.path,
        human_model_path=human_model_path,
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
    regionBounds: Optional[RegionBounds] = None
    includePolicy: bool = True
    includeOwnership: bool = False
    maxVisits: Optional[int] = None
    priority: int = 0
    overrideSettings: Optional[dict] = None

@app.post("/analyze")
async def analyze(request: MoveRequest):
    if not katago_wrapper:
        raise HTTPException(status_code=503, detail="KataGo engine not initialized")
    
    if request.gameId or request.userId:
        logger.info(f"Analysis request {request.id} for game={request.gameId}, user={request.userId}")
    
    query = request.model_dump(exclude_none=True)
    
    try:
        result = await katago_wrapper.query(query)
        return result
    except Exception as e:
        logger.error(f"Analysis failed (id={request.id}, game={request.gameId}, user={request.userId}): {e}")
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
         
    return {
        "status": "ok", 
        "pid": katago_wrapper.process.pid,
        "has_human_model": katago_wrapper.has_human_model
    }

async def _ensure_models_available(config: AppConfig) -> None:
    await _ensure_single_model(config.katago.model, "Main model")
    if config.katago.human_model:
        await _ensure_single_model(config.katago.human_model, "Human model")

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
        await loop.run_in_executor(None, _download_model, model.url, model.path, expected_sha)
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
        hasher = hashlib.sha256()
        try:
            if attempt > 0:
                logger.info(f"Downloading {url} (Attempt {attempt + 1}/{retries})")
            
            # Set a reasonable timeout (e.g., 30 seconds for connection)
            with urllib.request.urlopen(url, timeout=60) as response, open(tmp_path, "wb") as handle:
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
            return  # Success

        except Exception as e:
            last_error = e
            logger.warning(f"Download attempt {attempt + 1} failed: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            
            if attempt < retries - 1:
                sleep_time = 2 ** attempt  # Exponential backoff
                logger.info(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)

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
