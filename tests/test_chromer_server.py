import functools
import importlib.util
import json
import tempfile
import threading
import unittest
from collections import defaultdict, deque
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch


SERVER_PATH = Path(__file__).parents[1] / ".devcontainer" / "chromer_server.py"
SPEC = importlib.util.spec_from_file_location("chromer_server", SERVER_PATH)
chromer_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chromer_server)


class FeedbackEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "feedback.html").write_text("<h1>Feedback page</h1>", encoding="utf-8")
        self.feedback_file = self.root / "data" / "feedback.jsonl"
        chromer_server.FEEDBACK_FILE = self.feedback_file
        chromer_server.FeedbackHandler.submission_times = defaultdict(deque)

        handler = functools.partial(chromer_server.FeedbackHandler, directory=str(self.root))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp_dir.cleanup()

    def send_feedback(self, payload):
        request = Request(
            f"{self.base_url}/api/feedback",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        return response.code, json.loads(response.read())

    def test_feedback_port_serves_form_only_at_root(self):
        with urlopen(f"{self.base_url}/") as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"Feedback page", response.read())
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.base_url}/feedback.jsonl")
        self.assertEqual(error.exception.code, 404)

    def test_valid_feedback_is_stored_but_not_publicly_readable(self):
        status, response = self.send_feedback({
            "name": "Alex",
            "category": "idea",
            "message": "Add a new theme",
        })

        self.assertEqual(status, 201)
        self.assertEqual(response["message"], "Thanks for your feedback!")
        saved = json.loads(self.feedback_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["name"], "Alex")
        self.assertEqual(saved["message"], "Add a new theme")
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.base_url}/api/feedback")
        self.assertEqual(error.exception.code, 404)

    def test_invalid_feedback_is_rejected_without_writing(self):
        status, response = self.send_feedback({
            "name": "",
            "category": "idea",
            "message": "  ",
        })

        self.assertEqual(status, 400)
        self.assertIn("Message", response["error"])
        self.assertFalse(self.feedback_file.exists())

    def test_app_request_is_accepted_and_stored(self):
        status, response = self.send_feedback({
            "name": "Ryan",
            "category": "app_request",
            "message": "Please add Toby Books for School.",
        })

        self.assertEqual(status, 201)
        self.assertEqual(response["message"], "Thanks for your feedback!")
        saved = json.loads(self.feedback_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["category"], "app_request")
        self.assertEqual(saved["message"], "Please add Toby Books for School.")

    def test_rate_limit_rejects_excess_submissions(self):
        payload = {"name": "", "category": "other", "message": "Thanks!"}
        for _ in range(chromer_server.RATE_LIMIT_COUNT):
            status, _ = self.send_feedback(payload)
            self.assertEqual(status, 201)

        status, response = self.send_feedback(payload)
        self.assertEqual(status, 429)
        self.assertIn("Too many", response["error"])


class TobyNavigationEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        handler = functools.partial(chromer_server.ChromerHandler, directory=self.temp_dir.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp_dir.cleanup()

    def post_open_toby(self, origin):
        request = Request(
            f"{self.base_url}/api/open-toby",
            data=b"",
            headers={"Origin": origin},
            method="POST",
        )
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        return response.code, json.loads(response.read())

    def post_open_app(self, app_id, origin):
        request = Request(
            f"{self.base_url}/api/open-app",
            data=json.dumps({"app": app_id}).encode("utf-8"),
            headers={"Origin": origin, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        return response.code, json.loads(response.read())

    @patch.object(chromer_server.subprocess, "Popen")
    def test_same_origin_request_opens_fixed_toby_url(self, popen):
        status, response = self.post_open_toby(self.base_url)

        self.assertEqual(status, 202)
        self.assertEqual(response["message"], "Opening Toby in Chrome")
        command = popen.call_args.args[0]
        self.assertEqual(command[-1], chromer_server.TOBY_URL)
        self.assertIn("s6-setuidgid", command)

    @patch.object(chromer_server.subprocess, "Popen")
    def test_cross_origin_request_is_rejected(self, popen):
        status, response = self.post_open_toby("https://attacker.example")

        self.assertEqual(status, 403)
        self.assertIn("this homepage", response["error"])
        popen.assert_not_called()

    @patch.object(chromer_server.subprocess, "Popen")
    def test_same_origin_app_request_opens_selected_fixed_url(self, popen):
        status, response = self.post_open_app("balatro", self.base_url)

        self.assertEqual(status, 202)
        self.assertEqual(response["message"], "Opening Balatro in Chrome")
        command = popen.call_args.args[0]
        self.assertEqual(command[-1], chromer_server.APP_URLS["balatro"])

    @patch.object(chromer_server.subprocess, "Popen")
    def test_unknown_app_is_rejected(self, popen):
        status, response = self.post_open_app("https://attacker.example", self.base_url)

        self.assertEqual(status, 400)
        self.assertIn("valid app", response["error"])
        popen.assert_not_called()

    @patch.object(chromer_server.subprocess, "Popen", side_effect=OSError("Chrome unavailable"))
    def test_chrome_launch_failure_is_reported(self, popen):
        status, response = self.post_open_toby(self.base_url)

        self.assertEqual(status, 500)
        self.assertIn("Could not open Toby", response["error"])
        popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
