"""Loopback demo viewer for Metaflow's private local run metadata."""

import argparse
import re
from datetime import UTC, datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

FLOW = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
RUN = re.compile(r"[0-9]{1,24}")


def runs(root: Path):
    for path in root.glob("jobs/*/attempt-*/work/metaflow/.metaflow/*/*"):
        if (
            FLOW.fullmatch(path.parent.name)
            and RUN.fullmatch(path.name)
            and path.is_dir()
            and path.resolve().is_relative_to(root)
        ):
            yield path


def task_rows(path: Path) -> str:
    rows = []
    for step in path.iterdir():
        if (
            not FLOW.fullmatch(step.name)
            or not step.is_dir()
            or not step.resolve().is_relative_to(path.resolve())
        ):
            continue
        for task in step.iterdir():
            if (
                not RUN.fullmatch(task.name)
                or not task.is_dir()
                or not task.resolve().is_relative_to(path.resolve())
            ):
                continue
            done = list(task.glob("*.DONE.lock"))
            stamp = min(
                (file.stat().st_mtime for file in task.glob("*.data.json")),
                default=task.stat().st_mtime,
            )
            when = datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
            rows.append(
                (
                    stamp,
                    (
                        f"<tr><td>{escape(step.name)}</td><td>{escape(task.name)}</td>"
                        f"<td>{'Completed' if done else 'No completion recorded'}</td><td>{when}</td></tr>"
                    ),
                )
            )
    return "".join(row for _, row in sorted(rows))


class Viewer(BaseHTTPRequestHandler):
    root: Path

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            self.send_response(200)
            self.end_headers()
            return
        if path == "/":
            entries = {f"{run.parent.name}/{run.name}" for run in runs(self.root)}
            links = "".join(
                f'<li><a href="/flows/{entry}">{entry}</a></li>'
                for entry in sorted(entries, reverse=True)
            )
            self.page(
                "Metaflow runs",
                f"<ul>{links}</ul>" if links else "<p>No local runs yet.</p>",
            )
            return
        parts = path.split("/")
        if (
            len(parts) != 4
            or parts[1] != "flows"
            or not FLOW.fullmatch(parts[2])
            or not RUN.fullmatch(parts[3])
        ):
            self.send_error(404)
            return
        run = next(
            (
                run
                for run in runs(self.root)
                if (run.parent.name, run.name) == tuple(parts[2:])
            ),
            None,
        )
        if run is None:
            self.send_error(404, "Metaflow run not found in the local worker store")
            return
        rows = task_rows(run)
        self.page(
            f"{run.parent.name}/{run.name}",
            "<table><thead><tr><th>Step</th><th>Task</th><th>Status</th><th>Recorded time</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>",
        )

    def page(self, title: str, content: str):
        data = (
            f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{escape(title)}</title>'
            "<style>body{font:16px system-ui;margin:3rem;max-width:65rem}table{border-collapse:collapse}"
            "td,th{text-align:left;border-bottom:1px solid #ddd;padding:.65rem 1rem}</style>"
            f'<nav><a href="/">Metaflow runs</a></nav><h1>{escape(title)}</h1>{content}</html>'
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=58324)
    args = parser.parse_args()
    Viewer.root = args.root.resolve()
    ThreadingHTTPServer((args.host, args.port), Viewer).serve_forever()
