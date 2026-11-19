import argparse
import functools
import json
import os
import subprocess
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


FEEDBACK_FILE = Path(os.environ.get("CHROMER_FEEDBACK_FILE", "/config/chromer-feedback.jsonl"))
MAX_REQUEST_BYTES = 8192
MAX_FEEDBACK_BYTES = 1024 * 1024
MAX_MESSAGE_LENGTH = 1000
MAX_NAME_LENGTH = 80
RATE_LIMIT_COUNT = 5
RATE_LIMIT_WINDOW = 60
FEEDBACK_CATEGORIES = {"idea", "app_request", "bug", "other"}
TOBY_URL = "https://toby.booksforschool.online/"
APP_URLS = {
    "toby": TOBY_URL,
    "roblox": "https://www.roblox.com/",
    "balatro": "https://store.steampowered.com/app/2379780/Balatro/",
    "coolmathgames": "https://www.coolmathgames.com/",
    "googlechat": "https://chat.google.com",
    "googledocs": "https://docs.google.com",
    "youtube": "https://www.youtube.com",
}
APP_LABELS = {
    "toby": "Toby",
    "roblox": "Roblox",
    "balatro": "Balatro",
    "coolmathgames": "Coolmath Games",
    "googlechat": "Google Chat",
    "googledocs": "Google Docs",
    "youtube": "YouTube",
}


class FeedbackSubmissionMixin:
    feedback_lock = threading.Lock()
    submission_times = defaultdict(deque)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/feedback":
            self._send_json(404, {"error": "Not found"})
            return
        if self.headers.get_content_type() != "application/json":
            self._send_json(415, {"error": "Send feedback as JSON"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_json(400, {"error": "Invalid request length"})
            return
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "Feedback request is too large"})
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Invalid JSON"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "Feedback must be an object"})
            return

        name = payload.get("name", "")
        category = payload.get("category")
        message = payload.get("message")
        if not isinstance(name, str) or not isinstance(category, str) or not isinstance(message, str):
            self._send_json(400, {"error": "Name, category, and message must be text"})
            return

        name = name.strip()
        message = message.strip()
        if len(name) > MAX_NAME_LENGTH:
            self._send_json(400, {"error": f"Name must be {MAX_NAME_LENGTH} characters or fewer"})
            return
        if category not in FEEDBACK_CATEGORIES:
            self._send_json(400, {"error": "Choose a valid feedback type"})
            return
        if not message or len(message) > MAX_MESSAGE_LENGTH:
            self._send_json(400, {"error": f"Message must be 1 to {MAX_MESSAGE_LENGTH} characters"})
            return

        client_ip = self.client_address[0]
        now = time.monotonic()
        record = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "name": name,
            "category": category,
            "message": message,
        }
        serialized_record = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")

        with self.feedback_lock:
            recent_submissions = self.submission_times[client_ip]
            while recent_submissions and now - recent_submissions[0] >= RATE_LIMIT_WINDOW:
                recent_submissions.popleft()
            if len(recent_submissions) >= RATE_LIMIT_COUNT:
                self._send_json(429, {"error": "Too many submissions. Please try again in a minute."})
                return

            try:
                FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
                with FEEDBACK_FILE.open("ab") as feedback_file:
                    if feedback_file.tell() + len(serialized_record) > MAX_FEEDBACK_BYTES:
                        self._send_json(507, {"error": "Feedback storage is full"})
                        return
                    feedback_file.write(serialized_record)
            except OSError:
                self.log_error("Could not save feedback to %s", FEEDBACK_FILE)
                self._send_json(500, {"error": "Could not save feedback. Please try again later."})
                return

            recent_submissions.append(now)

        self._send_json(201, {"message": "Thanks for your feedback!"})

    def _send_json(self, status, payload):
        response = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(response)


class ChromerHandler(FeedbackSubmissionMixin, SimpleHTTPRequestHandler):
    def __init__(self, *args, directory="/workspaces/chromer-thebest", **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def do_POST(self):
        request_path = urlsplit(self.path).path
        if request_path not in {"/api/open-toby", "/api/open-app"}:
            super().do_POST()
            return

        origin = urlsplit(self.headers.get("Origin", ""))
        host = self.headers.get("Host", "")
        if origin.scheme not in {"http", "https"} or origin.netloc.lower() != host.lower():
            self._send_json(403, {"error": "Request must come from this homepage"})
            return

        app_id = "toby"
        if request_path == "/api/open-app":
            if self.headers.get_content_type() != "application/json":
                self._send_json(415, {"error": "Send app requests as JSON"})
                return

            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send_json(400, {"error": "Invalid request length"})
                return
            if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
                self._send_json(413, {"error": "App request is too large"})
                return

            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"error": "Invalid JSON"})
                return
            if not isinstance(payload, dict) or not isinstance(payload.get("app"), str):
                self._send_json(400, {"error": "Choose a valid app"})
                return
            app_id = payload["app"]

        if app_id not in APP_URLS:
            self._send_json(400, {"error": "Choose a valid app"})
            return

        app_label = APP_LABELS[app_id]
        try:
            subprocess.Popen(
                [
                    "s6-setuidgid",
                    "abc",
                    "env",
                    "WAYLAND_DISPLAY=wayland-1",
                    "/usr/bin/google-chrome",
                    "--no-sandbox",
                    "--ozone-platform=wayland",
                    APP_URLS[app_id],
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as error:
            self.log_error("Could not open %s in Chrome: %s", app_label, error)
            self._send_json(500, {"error": f"Could not open {app_label} in Chrome"})
            return

        self._send_json(202, {"message": f"Opening {app_label} in Chrome"})


class FeedbackHandler(FeedbackSubmissionMixin, SimpleHTTPRequestHandler):
    def __init__(self, *args, directory="/workspaces/chromer-thebest", **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        if urlsplit(self.path).path not in {"/", "/index.html"}:
            self._send_json(404, {"error": "Not found"})
            return

        self.path = "/feedback.html"
        super().do_GET()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default="/workspaces/chromer-thebest")
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    handler = functools.partial(ChromerHandler, directory=args.directory)
    feedback_handler = functools.partial(FeedbackHandler, directory=args.directory)

    homepage_server = ThreadingHTTPServer((args.host, 43083), handler)
    feedback_server = ThreadingHTTPServer((args.host, 43084), feedback_handler)
    feedback_thread = threading.Thread(target=feedback_server.serve_forever, daemon=True)
    feedback_thread.start()
    print("Chromer homepage listening on port 43083", flush=True)
    print("Chromer feedback listening on port 43084", flush=True)
    homepage_server.serve_forever()


if __name__ == "__main__":
    main()
