import unittest
import json
import time
import threading
from unittest.mock import MagicMock, patch
from io import StringIO
from realtime_api.models import AnalysisRequest, AnalysisResponse, MoveInfo
from realtime_api.engine import KataGoEngine

class TestModels(unittest.TestCase):
    def test_request_to_dict(self):
        req = AnalysisRequest(
            id="test_1",
            moves=[("B", "Q4")],
            maxVisits=100
        )
        data = req.to_dict()
        self.assertEqual(data["id"], "test_1")
        self.assertEqual(data["moves"], [("B", "Q4")])
        self.assertEqual(data["maxVisits"], 100)
        self.assertEqual(data["rules"], "chinese") # default

    def test_response_from_dict(self):
        data = {
            "id": "test_1",
            "isDuringSearch": False,
            "moveInfos": [
                {
                    "move": "Q4",
                    "visits": 10,
                    "winrate": 0.55,
                    "scoreLead": 1.5,
                    "scoreSelfplay": 2.0,
                    "utility": 0.1,
                    "prior": 0.05,
                    "order": 0,
                    "pv": ["Q4", "D4"]
                }
            ],
            "rootInfo": {
                "winrate": 0.54,
                "scoreLead": 1.4,
                "visits": 10,
                "utility": 0.09
            }
        }
        resp = AnalysisResponse.from_dict(data)
        self.assertEqual(resp.id, "test_1")
        self.assertFalse(resp.isDuringSearch)
        self.assertEqual(len(resp.moveInfos), 1)
        self.assertEqual(resp.moveInfos[0].move, "Q4")
        self.assertIsNotNone(resp.rootInfo)
        self.assertEqual(resp.rootInfo.winrate, 0.54)

class TestEngine(unittest.TestCase):
    @patch("subprocess.Popen")
    def test_engine_initialization(self, mock_popen):
        mock_process = MagicMock()
        mock_popen.return_value = mock_process
        mock_process.stdout.readline.side_effect = ["", ""] # End immediately
        mock_process.stderr.readline.side_effect = ["", ""]
        
        engine = KataGoEngine("katago", "config.cfg", "model.bin.gz")
        
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        self.assertIn("katago", args)
        self.assertIn("analysis", args)
        
        engine.stop()

    @patch("subprocess.Popen")
    def test_submit_analysis(self, mock_popen):
        mock_process = MagicMock()
        mock_popen.return_value = mock_process
        
        # Simulate stdout returning a response then empty string to finish thread
        response_data = {
            "id": "req_1",
            "isDuringSearch": False,
            "moveInfos": []
        }
        
        ready_event = threading.Event()

        # Use an iterator to yield responses, with a delay before EOF
        responses = iter([json.dumps(response_data) + "\n", ""])
        def delayed_readline():
            # Wait for signal before first response
            if not ready_event.is_set():
                ready_event.wait(timeout=2.0)
            
            try:
                val = next(responses)
                if val == "":
                    time.sleep(0.2) # Keep alive long enough for check
                return val
            except StopIteration:
                return ""

        mock_process.stdout.readline.side_effect = delayed_readline
        mock_process.stderr.readline.side_effect = [""] # No stderr
        
        engine = KataGoEngine("katago", "config.cfg", "model.bin.gz")
        
        received_response = None
        def callback(resp):
            nonlocal received_response
            received_response = resp
            
        req = AnalysisRequest(id="req_1", moves=[])
        engine.submit_analysis(req, callback)
        
        # Signal that request is submitted, allow response to flow
        ready_event.set()

        # Give threads a moment to process
        time.sleep(0.2)
        
        self.assertIsNotNone(received_response)
        self.assertEqual(received_response.id, "req_1")
        
        # Check if stdin was written to
        mock_process.stdin.write.assert_called()
        written_data = mock_process.stdin.write.call_args[0][0]
        parsed_written = json.loads(written_data)
        self.assertEqual(parsed_written["id"], "req_1")
        
        engine.stop()

if __name__ == '__main__':
    unittest.main()
