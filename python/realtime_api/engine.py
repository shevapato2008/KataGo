import subprocess
import json
import threading
import time
from typing import Optional, Dict, List, Callable, Any
from .models import AnalysisRequest, AnalysisResponse

class KataGoEngine:
    def __init__(self, katago_path: str, config_path: str, model_path: str, additional_args: List[str] = None):
        if additional_args is None:
            additional_args = []
            
        cmd = [katago_path, "analysis", "-config", config_path, "-model", model_path] + additional_args
        
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,  # Handle text streams directly
            bufsize=1   # Line buffered
        )
        
        self._running = True
        self._callbacks: Dict[str, Callable[[AnalysisResponse], None]] = {}
        self._lock = threading.Lock()
        
        # Start threads for reading stdout and stderr
        self.stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self.stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()

    def submit_analysis(self, request: AnalysisRequest, callback: Optional[Callable[[AnalysisResponse], None]] = None) -> None:
        """
        Submits an analysis request to the engine.
        
        Args:
            request: The AnalysisRequest object.
            callback: Optional function to call with the AnalysisResponse. 
                      If not provided, the response handles just logging/ignoring (for now).
                      In a real async system, this would resolve a Future.
        """
        if not self._running:
            raise RuntimeError("KataGo engine is not running")

        with self._lock:
            if callback:
                self._callbacks[request.id] = callback
        
        try:
            json_str = json.dumps(request.to_dict())
            if self.process.stdin:
                self.process.stdin.write(json_str + "\n")
                self.process.stdin.flush()
        except (BrokenPipeError, IOError) as e:
            self._running = False
            raise RuntimeError(f"Failed to write to KataGo: {e}")

    def _read_stdout(self):
        """Loop to read responses from KataGo stdout."""
        while self._running and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break
                
                if line.strip():
                    self._handle_response_line(line)
                    
            except Exception as e:
                print(f"Error reading stdout: {e}")
                break
        
        self._running = False

    def _read_stderr(self):
        """Loop to read logging from KataGo stderr."""
        while self._running and self.process.stderr:
            try:
                line = self.process.stderr.readline()
                if not line:
                    break
                # In a real app, log this properly. For prototype, maybe just pass.
                # print(f"KataGo Log: {line.strip()}") 
            except Exception as e:
                print(f"Error reading stderr: {e}")
                break

    def _handle_response_line(self, line: str):
        try:
            data = json.loads(line)
            response = AnalysisResponse.from_dict(data)
            
            # Find callback
            request_id = response.id
            callback = None
            
            # If it is the final result (not during search), remove the callback
            # Unless we want to support streaming updates, in which case we keep it.
            # For this prototype, let's assume one-shot response or we keep callback until explicitly removed?
            # The Analysis Engine doc says: "isDuringSearch: false" means done.
            
            with self._lock:
                if request_id in self._callbacks:
                    callback = self._callbacks[request_id]
                    if not response.isDuringSearch:
                        del self._callbacks[request_id]
            
            if callback:
                callback(response)
                
        except json.JSONDecodeError:
            print(f"Failed to decode JSON: {line}")
        except Exception as e:
            print(f"Error processing response: {e}")

    def stop(self):
        self._running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
