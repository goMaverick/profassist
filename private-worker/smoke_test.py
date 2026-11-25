"""Exercise the HTTP shim against a fake CLI without model files or Docker."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def request(port: int, method: str, path: str, body: dict | None = None, token: str | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    encoded = json.dumps(body).encode() if body is not None else None
    connection.request(method, path, body=encoded, headers=headers)
    response = connection.getresponse()
    result = response.status, json.loads(response.read())
    connection.close()
    return result


def main() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    with tempfile.TemporaryDirectory(prefix="profassist-worker-smoke-") as tmp:
        root = Path(tmp)
        fake_module = root / "fake" / "profassist_worker"
        fake_module.mkdir(parents=True)
        (fake_module / "__main__.py").write_text(
            """
import argparse, json, os
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('operation'); p.add_argument('--input'); p.add_argument('--output'); p.add_argument('--work-dir'); a=p.parse_args()
with open(a.input) as f: envelope=json.load(f)
counter=Path(os.environ['FAKE_ATTEMPT_COUNT'])
count=int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(count + 1))
artifact=Path(a.work_dir) / 'artifact.txt'
if count == 0:
    artifact.write_text('failed attempt')
    with open(a.output, 'w') as f: json.dump({'partial': True}, f)
    raise SystemExit(2)
assert not artifact.exists()
artifact.write_text('completed attempt')
with open(a.output, 'w') as f: json.dump({'schema_version':1,'operation':a.operation,'status':'completed','result':{'job_id':envelope['context']['job_id'],'tracking_uri':envelope['context']['tracking_uri'],'encoder_dir':envelope['context']['encoder_dir']},'artifacts':{}}, f)
"""
        )
        (fake_module / "__init__.py").write_text("")
        env = os.environ.copy()
        env.update(
            {
                "PORT": str(port),
                "PROFASSIST_WORKER_TOKEN": "smoke-test-secret",
                "PROFASSIST_WORKER_STORE": str(root / "store"),
                "PROFASSIST_WORKER_TIMEOUT_SECONDS": "10",
                "MLFLOW_TRACKING_URI": "http://mlflow.local:5000",
                "FAKE_ATTEMPT_COUNT": str(root / "attempt-count"),
                "PYTHONPATH": str(root / "fake") + os.pathsep + env.get("PYTHONPATH", ""),
            }
        )
        server = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("server.py"))],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(50):
                try:
                    assert request(port, "GET", "/health")[0] == 200
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("worker shim did not start")

            operation = "dropout-score"
            job_id = "e79a4b61-72bb-47e2-9375-a30ba8a4e80e"
            envelope = {
                "schema_version": 1,
                "operation": operation,
                "context": {
                    "job_id": job_id,
                    "organization_id": "org/../../private",
                    "course_id": "course-a",
                },
                "payload": {"input_file": "snapshots.csv"},
            }
            assert request(port, "POST", f"/jobs/{operation}", envelope)[0] == 401
            failed_status, failed = request(port, "POST", f"/jobs/{operation}", envelope, "smoke-test-secret")
            assert failed_status == 502 and failed == {"error": "worker_failed"}
            status, first = request(port, "POST", f"/jobs/{operation}", envelope, "smoke-test-secret")
            assert status == 200 and first["result"]["job_id"] == job_id
            assert first["result"]["tracking_uri"] == "http://mlflow.local:5000"
            assert first["result"]["encoder_dir"] == "/app/models/minilm"
            assert request(port, "POST", f"/jobs/{operation}", envelope, "smoke-test-secret") == (200, first)
            changed = {**envelope, "payload": {"input_file": "other.csv"}}
            assert request(port, "POST", f"/jobs/{operation}", changed, "smoke-test-secret")[0] == 409
            assert request(port, "POST", "/jobs/../../etc/passwd", envelope, "smoke-test-secret")[0] == 404
            job_dir = root / "store" / "jobs" / job_id
            assert (job_dir / "request.json").exists() and (job_dir / "result.json").exists()
            artifacts = list(job_dir.glob("attempt-*/work/artifact.txt"))
            assert len(artifacts) == 1 and artifacts[0].read_text() == "completed attempt"
            assert (root / "attempt-count").read_text() == "2"
            scope_dirs = list((root / "store" / "scopes").iterdir())
            assert len(scope_dirs) == 1 and len(scope_dirs[0].name) == 32
        finally:
            server.terminate()
            server.wait(timeout=5)
    print("private worker shim fake-CLI smoke passed")


if __name__ == "__main__":
    main()
