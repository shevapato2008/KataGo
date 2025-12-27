import os
import logging
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional, Tuple, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from .katago_wrapper import KataGoWrapper

# Load environment variables from .env file if present
load_dotenv()

# Configuration
# Default paths assume running from the root of the repo
KATAGO_PATH = os.getenv("KATAGO_PATH", "./cpp/katago")
KATAGO_CONFIG_PATH = os.getenv("KATAGO_CONFIG_PATH", "./cpp/configs/analysis_example.cfg")
KATAGO_MODEL_PATH = os.getenv("KATAGO_MODEL_PATH", "model.bin.gz") 

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("realtime_api")

katago_wrapper: Optional[KataGoWrapper] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global katago_wrapper
    
    # In a real deployment, we might want to fail fast if model is missing.
    # For now, we initialize and let the wrapper handle startup errors or wait for first request.
    logger.info(f"Initializing KataGo Wrapper with: Bin={KATAGO_PATH}, Config={KATAGO_CONFIG_PATH}, Model={KATAGO_MODEL_PATH}")
    
    katago_wrapper = KataGoWrapper(KATAGO_PATH, KATAGO_CONFIG_PATH, KATAGO_MODEL_PATH)
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

if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    
    # We use the import string "realtime_api.main:app" so that reload works
    uvicorn.run("realtime_api.main:app", host=host, port=port, reload=True)