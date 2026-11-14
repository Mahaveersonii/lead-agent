"""Lead Agent dashboard: a local web page with buttons for setup check, test run, live run and run history.

    python dashboard.py        opens http://127.0.0.1:8765 in the browser

Only this computer can reach it (it listens on 127.0.0.1). It runs the same run.py / check_setup.py
as the double-click files, so the pipeline behaves exactly the same.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import threading
import webbrowser
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from lead_agent.common import ROOT, load_config

PORT = int(os.environ.get("LEAD_AGENT_PORT", "8765"))
PAGE = ROOT / "ui" / "index.html"
cfg = load_config()
INCOMING = ROOT / cfg["paths"]["incoming"]
OUTPUT = ROOT / cfg["paths"]["output"]
LOGS = OUTPUT / "logs"

JOBS = {
    "check": ("Setup check", ["check_setup.py"]),
    "test": ("Test run (free)", ["run.py"]),
    "test_verify": ("Test run + Bouncify", ["run.py", "--verify"]),
    "live": ("LIVE run", ["run.py", "--live"]),
    "podcasts": ("Podcast search", ["find_podcasts.py"]),
}
TABLE_COLUMNS = ["status", "reason", "decision", "rule_score", "industry", "signals", "source", "email", "first_name",
                 "full_name", "username", "podcast", "niche", "fit_score",
                 "verification", "followers", "personalization", "profile_url"]


class Job:
    """One pipeline process at a time; its output is kept in memory and saved to output/logs."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.kind = ""
        self.lines: list[str] = []
        self.started = ""
        self.exit_code: int | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, kind: str, extra: list[str] | None = None) -> None:
        with self.lock:
            if self.running:
                raise RuntimeError("Another run is still going. Wait for it to finish or press Stop.")
            self.kind, self.lines, self.exit_code = kind, [], None
            self.started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            self.proc = subprocess.Popen([sys.executable, "-W", "ignore", *JOBS[kind][1], *(extra or [])], cwd=ROOT, env=env,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc: subprocess.Popen) -> None:
        """Keep each line in memory for the page and write it to the log file straight away,
        so the log is readable even while a run is still going or if the window is closed."""
        LOGS.mkdir(parents=True, exist_ok=True)
        stamp = self.started.replace("-", "").replace(":", "").replace(" ", "-")
        with open(LOGS / f"{stamp}-{self.kind}.log", "w", encoding="utf-8") as log_file:
            for line in proc.stdout:
                self.lines.append(line.rstrip("\n"))
                log_file.write(line if line.endswith("\n") else line + "\n")
                log_file.flush()
            self.exit_code = proc.wait()
            end = f"--- finished ({'OK' if self.exit_code == 0 else 'stopped with a problem'}, exit code {self.exit_code}) ---"
            self.lines.append(end)
            log_file.write(end + "\n")

    def stop(self) -> None:
        if self.running:
            self.proc.terminate()

    def state(self, since: int) -> dict:
        return {"kind": self.kind, "label": JOBS.get(self.kind, ("",))[0], "running": self.running,
                "started": self.started, "exit_code": self.exit_code,
                "lines": self.lines[since:], "total": len(self.lines)}


JOB = Job()


def incoming_files() -> list[dict]:
    files = []
    for path in sorted(INCOMING.glob("*.csv")):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            rows = sum(1 for _ in csv.DictReader(f))
        files.append({"name": path.name, "rows": rows,
                      "added": datetime.fromtimestamp(path.stat().st_mtime).strftime("%d %b %H:%M")})
    return files


def read_report(name: str) -> list[dict]:
    path = OUTPUT / Path(name).name
    if not path.is_file() or path.suffix != ".csv":
        raise FileNotFoundError(name)
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def history() -> list[dict]:
    runs = []
    for path in sorted(OUTPUT.glob("run-*.csv"), reverse=True)[:50]:
        rows = read_report(path.name)
        counts = Counter(r["status"] for r in rows)
        live = "Sent" in counts or not any("dry run" in s for s in counts)
        when = datetime.strptime(path.stem[4:], "%Y%m%d-%H%M%S")
        runs.append({"file": path.name, "when": when.strftime("%a %d %b %Y, %H:%M"), "type": "LIVE" if live else "Test",
                     "total": len(rows), "rejected": counts.get("Rejected", 0),
                     "passed": len(rows) - counts.get("Rejected", 0), "sent": counts.get("Sent", 0)})
    return runs


def report_detail(name: str) -> dict:
    rows = read_report(name)
    reasons = Counter(r["reason"] for r in rows if r["status"] == "Rejected")
    return {"file": Path(name).name, "columns": TABLE_COLUMNS,
            "rows": [{c: r.get(c, "") for c in TABLE_COLUMNS} for r in rows],
            "reasons": reasons.most_common(12)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep the Terminal window quiet
        pass

    def _send(self, body: bytes, kind: str = "application/json", status: int = 200, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(json.dumps(data).encode(), status=status)

    def _local_only(self) -> bool:
        """Refuse requests from other websites open in the same browser."""
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        allowed = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
        return host in allowed and (not origin or urlparse(origin).netloc in allowed)

    def do_GET(self) -> None:
        if not self._local_only():
            return self._json({"error": "local use only"}, 403)
        url = urlparse(self.path)
        query = parse_qs(url.query)
        try:
            if url.path == "/":
                return self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            if url.path == "/api/files":
                return self._json(incoming_files())
            if url.path == "/api/job":
                return self._json(JOB.state(int(query.get("since", ["0"])[0])))
            if url.path == "/api/history":
                return self._json(history())
            if url.path == "/api/report":
                return self._json(report_detail(query["file"][0]))
            if url.path == "/api/download":
                name = Path(query["file"][0]).name
                body = (OUTPUT / name).read_bytes()
                return self._send(body, "text/csv", extra={"Content-Disposition": f"attachment; filename={quote(name)}"})
            return self._json({"error": "not found"}, 404)
        except (FileNotFoundError, KeyError):
            return self._json({"error": "file not found"}, 404)

    def do_POST(self) -> None:
        if not self._local_only():
            return self._json({"error": "local use only"}, 403)
        url = urlparse(self.path)
        query = parse_qs(url.query)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            if url.path == "/api/upload":
                name = Path(query["name"][0]).name
                if not name.lower().endswith(".csv"):
                    return self._json({"error": "Only .csv files from IG Email Extractor"}, 400)
                if not body.lstrip(b"\xef\xbb\xbf").startswith(b"User Id"):
                    return self._json({"error": f"{name} does not look like an IG Email Extractor export"}, 400)
                INCOMING.mkdir(parents=True, exist_ok=True)
                (INCOMING / name).write_bytes(body)
                return self._json({"ok": True})
            if url.path == "/api/remove":
                (INCOMING / Path(query["name"][0]).name).unlink(missing_ok=True)
                return self._json({"ok": True})
            if url.path == "/api/run":
                kind = query.get("kind", [""])[0]
                if kind not in JOBS:
                    return self._json({"error": "unknown run type"}, 400)
                options = json.loads(body or b"{}")
                if kind == "live" and options.get("confirm") != "YES":
                    return self._json({"error": "Type YES to start a live run"}, 400)
                extra = []
                if kind == "podcasts" and str(options.get("keywords", "")).strip():
                    keywords = str(options["keywords"]).replace("\n", ",")[:2000]
                    extra = [f"--keywords={keywords}"]  # one argument, never through a shell
                JOB.start(kind, extra)
                return self._json({"ok": True})
            if url.path == "/api/stop":
                JOB.stop()
                return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)
        except ValueError:
            return self._json({"error": "bad request"}, 400)
        except RuntimeError as problem:
            return self._json({"error": str(problem)}, 409)


def main() -> None:
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"The dashboard is already open. Opening http://127.0.0.1:{PORT}")
        webbrowser.open(f"http://127.0.0.1:{PORT}")
        return
    print(f"Lead Agent dashboard: http://127.0.0.1:{PORT}")
    print("Keep this window open while you use the dashboard. Close it (or press Ctrl+C) to stop.")
    if not os.environ.get("LEAD_AGENT_NO_BROWSER"):
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        JOB.stop()


if __name__ == "__main__":
    main()
