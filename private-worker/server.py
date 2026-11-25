"""Private HTTP boundary for the ProfAssist model worker CLI.

This module intentionally uses only the standard library so it can be layered
onto the upstream, dependency-heavy worker image without changing its model
environment.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


OPERATIONS = frozenset(
    {
        "plagiarism-score",
        "plagiarism-snapshot",
        "plagiarism-train",
        "plagiarism-verify-release",
        "dropout-score",
        "dropout-train",
        "dropout-verify-release",
        "dropout-monitor",
    }
)
MAX_REQUEST_BYTES = 160 * 1024 * 1024
STORE = Path(os.environ.get("PROFASSIST_WORKER_STORE", "/var/lib/profassist-worker"))
TOKEN = os.environ.get("PROFASSIST_WORKER_TOKEN", "")
TIMEOUT = max(1, int(os.environ.get("PROFASSIST_WORKER_TIMEOUT_SECONDS", "300")))
TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000").rstrip("/")
ENCODER_DIR = "/app/models/minilm"
_job_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _scope_key(context: dict[str, Any]) -> str:
    scope = context.get("scope")
    if not isinstance(scope, dict) or not scope:
        scope = {
            key: context.get(key)
            for key in ("organization_id", "institution_id", "course_id", "assignment_id")
            if context.get(key) is not None
        }
    # Do not include user-controlled names, paths, or requester identity in a path.
    digest = hashlib.sha256(_json_bytes(scope)).hexdigest()
    return digest[:32]


def _job_id(context: dict[str, Any], envelope: dict[str, Any]) -> str:
    value = context.get("job_id", envelope.get("job_id"))
    return str(uuid.UUID(str(value)))


def _job_lock(job_id: str) -> threading.Lock:
    with _locks_guard:
        return _job_locks.setdefault(job_id, threading.Lock())


class Handler(BaseHTTPRequestHandler):
    server_version = "ProfAssistPrivateWorker/1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Request bodies and model inputs are deliberately never logged.
        sys.stderr.write("profassist-worker %s - %s\n" % (self.address_string(), fmt % args))

    def _respond(self, status: int, body: dict[str, Any]) -> None:
        data = _json_bytes(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/health":
            self._respond(200, {"status": "ok"})
        else:
            self._respond(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        match = re.fullmatch(r"/jobs/([a-z0-9-]+)", path)
        if not match or match.group(1) not in OPERATIONS:
            self._respond(404, {"error": "not_found"})
            return
        if not TOKEN:
            self._respond(503, {"error": "worker_not_configured"})
            return
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {TOKEN}"
        if not hmac.compare_digest(supplied, expected):
            self._respond(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._respond(400, {"error": "invalid_content_length"})
            return
        if length < 1 or length > MAX_REQUEST_BYTES:
            self._respond(413, {"error": "request_too_large"})
            return
        try:
            envelope = json.loads(self.rfile.read(length))
            operation = match.group(1)
            if not isinstance(envelope, dict) or envelope.get("schema_version") != 1:
                raise ValueError("invalid envelope")
            if envelope.get("operation") != operation:
                raise ValueError("operation mismatch")
            context = envelope.get("context")
            if not isinstance(context, dict) or not isinstance(envelope.get("payload"), dict):
                raise ValueError("invalid context or payload")
            job_id = _job_id(context, envelope)
            # Registry and encoder locations are deployment-owned settings. Do
            # not let an API caller redirect model access or choose host paths.
            envelope["context"] = {
                **context,
                "tracking_uri": TRACKING_URI,
                "encoder_dir": ENCODER_DIR,
            }
            context = envelope["context"]
        except (ValueError, TypeError, json.JSONDecodeError):
            self._respond(400, {"error": "invalid_request"})
            return

        with _job_lock(job_id):
            try:
                result = self._execute(operation, envelope, context, job_id)
            except FileExistsError:
                self._respond(409, {"error": "job_id_conflict"})
            except subprocess.TimeoutExpired:
                self._respond(504, {"error": "worker_timeout"})
            except Exception:
                # Do not return paths, input values, credentials, or CLI stderr.
                self._respond(502, {"error": "worker_failed"})
            else:
                self._respond(200, result)

    def _execute(
        self, operation: str, envelope: dict[str, Any], context: dict[str, Any], job_id: str
    ) -> dict[str, Any]:
        job_dir = STORE / "jobs" / job_id
        scope_dir = STORE / "scopes" / _scope_key(context)
        job_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        scope_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        request_path = job_dir / "request.json"
        output_path = job_dir / "result.json"
        request_bytes = _json_bytes(envelope)

        if request_path.exists():
            if request_path.read_bytes() != request_bytes:
                raise FileExistsError
            if output_path.exists():
                cached = json.loads(output_path.read_text())
                if isinstance(cached, dict):
                    return cached
        else:
            _write_private(request_path, request_bytes)

        env = os.environ.copy()
        env["PROFASSIST_WORKER_SCOPE_DIR"] = str(scope_dir)
        env["PROFASSIST_WORKER_JOB_DIR"] = str(job_dir)
        # A failed Metaflow attempt may leave its result path behind. Give each
        # uncached execution an isolated directory so a retry of the same
        # envelope starts clean. Keep the completed attempt's private artifacts.
        attempt_dir = Path(tempfile.mkdtemp(prefix="attempt-", dir=job_dir))
        try:
            work_dir = attempt_dir / "work"
            work_dir.mkdir(mode=0o700)
            cli_output = attempt_dir / "cli-result.json"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "profassist_worker",
                    operation,
                    "--input",
                    str(request_path),
                    "--output",
                    str(cli_output),
                    "--work-dir",
                    str(work_dir),
                ],
                check=True,
                capture_output=True,
                timeout=TIMEOUT,
                env=env,
            )
            result = json.loads(cli_output.read_text())
            if (
                not isinstance(result, dict)
                or result.get("schema_version") != 1
                or result.get("operation") != operation
                or result.get("status") != "completed"
            ):
                raise ValueError("invalid worker result")
            _write_private(output_path, _json_bytes(result))
        except Exception:
            shutil.rmtree(attempt_dir)
            raise
        return result


def _write_private(path: Path, data: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main() -> None:
    if not TOKEN:
        raise SystemExit("PROFASSIST_WORKER_TOKEN must be configured")
    STORE.mkdir(parents=True, exist_ok=True, mode=0o700)
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8081"))), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
