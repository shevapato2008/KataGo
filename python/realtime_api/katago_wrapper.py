import asyncio
import json
import logging
import uuid
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class KataGoWrapper:
    def __init__(self, katago_path: str, config_path: str, model_path: str, additional_args: list[str] = None):
        self.katago_path = katago_path
        self.config_path = config_path
        self.model_path = model_path
        self.additional_args = additional_args or []
        self.process: Optional[asyncio.subprocess.Process] = None
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.running = False
        self.read_task: Optional[asyncio.Task] = None

    async def start(self):
        if self.process:
            return

        cmd = [
            self.katago_path,
            "analysis",
            "-config", self.config_path,
            "-model", self.model_path,
            *self.additional_args
        ]
        
        logger.info(f"Starting KataGo: {' '.join(cmd)}")
        
        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self.running = True
            self.read_task = asyncio.create_task(self._read_loop())
            asyncio.create_task(self._log_stderr())
        except Exception as e:
            logger.error(f"Failed to start KataGo: {e}")
            raise

    async def stop(self):
        self.running = False
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except ProcessLookupError:
                pass
            self.process = None
        
        # Cancel pending requests
        for future in self.pending_requests.values():
            if not future.done():
                future.cancel()
        self.pending_requests.clear()

    async def query(self, query_data: Dict[str, Any]) -> Dict[str, Any]:
        if not self.process or self.process.returncode is not None:
            # If process crashed or hasn't started, try to start it
            await self.start()
        
        query_id = query_data.get("id")
        if not query_id:
            query_id = str(uuid.uuid4())
            query_data["id"] = query_id
        
        future = asyncio.get_running_loop().create_future()
        self.pending_requests[query_id] = future
        
        try:
            json_str = json.dumps(query_data) + "\n"
            self.process.stdin.write(json_str.encode())
            await self.process.stdin.drain()
            return await future
        except Exception as e:
            if query_id in self.pending_requests:
                del self.pending_requests[query_id]
            raise e

    async def _read_loop(self):
        while self.running and self.process:
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break
                line_str = line.decode().strip()
                if not line_str:
                    continue
                
                try:
                    response = json.loads(line_str)
                    req_id = response.get("id")
                    if req_id and req_id in self.pending_requests:
                        future = self.pending_requests.pop(req_id)
                        if not future.done():
                            future.set_result(response)
                except json.JSONDecodeError:
                    logger.error(f"Failed to decode JSON: {line_str}")
            except Exception as e:
                logger.error(f"Error reading from KataGo: {e}")
                break
        
        logger.warning("KataGo read loop exited")
        # Fail all pending requests if process dies
        for future in self.pending_requests.values():
            if not future.done():
                future.set_exception(RuntimeError("KataGo process terminated"))
        self.pending_requests.clear()

    async def _log_stderr(self):
        while self.running and self.process:
            try:
                line = await self.process.stderr.readline()
                if not line:
                    break
                # Only log if it looks like an error or explicit log
                # For now just debug or ignore to avoid clutter
                # logger.debug(f"KataGo Stderr: {line.decode().strip()}")
            except:
                break
