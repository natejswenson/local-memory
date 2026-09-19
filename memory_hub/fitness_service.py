"""Authenticated, single-host writer. No OpenAI credentials or model calls."""

import argparse
import fcntl
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import sys
import threading

from memory_hub.fitness_store import FitnessStore, safe


def serve(config_path):
    config = json.loads(safe(config_path).read_text())
    control = safe(config["control"])
    lease = open(control / "writer.lock", "a+")
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    token = safe(config["token_file"]).read_text().strip()
    if len(token) < 32:
        raise ValueError("A local service token of at least 32 characters is required")
    sys.path.insert(0, str(Path(config["fitness_repo"]) / "src"))
    os.environ["LOCAL_FITNESS_PREFERENCES_BACKEND"] = "legacy"
    os.environ["LOCAL_FITNESS_JOURNAL_BACKEND"] = "legacy"
    from local_fitness import notes
    from local_fitness.agent import journal

    store = FitnessStore(config["vault"], control, notes, journal, config["backup_dir"])

    # Capture sequential Obsidian edits even when no application writes occur.
    def periodic_backup():
        while True:
            try:
                with store.lock:
                    store.recover()
                    store.backup()
                (control / "backup-error").unlink(missing_ok=True)
            except Exception:
                logging.exception("Scheduled fitness backup failed")
                (control / "backup-error").write_text(
                    "Inspect writer log; last backup failed\n"
                )
            threading.Event().wait(3600)

    threading.Thread(target=periodic_backup, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != "/memory" or not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + token
            ):
                self.send_error(403)
                return
            self.connection.settimeout(10)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 65536:
                    raise ValueError("Invalid request size")
                request = json.loads(self.rfile.read(size))
                if set(request) - {"operation", "args", "request_id"}:
                    raise ValueError("Unknown fields")
                if not isinstance(request.get("args", {}), dict):
                    raise ValueError("args must be an object")
                result = store.request(
                    request["operation"],
                    request.get("args", {}),
                    request.get("request_id"),
                )
                payload = {"ok": True, "result": result}
                status = 200
            except (ValueError, TypeError, KeyError) as exc:
                payload = {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
                status = 400
            except Exception as exc:
                import sqlite3

                if isinstance(exc, sqlite3.IntegrityError):
                    payload = {
                        "ok": False,
                        "error": "Duplicate fitness event",
                        "error_type": "IntegrityError",
                    }
                    status = 409
                else:
                    logging.exception("Fitness memory operation failed")
                    payload = {
                        "ok": False,
                        "error": "Memory unavailable; inspect writer status",
                        "error_type": "Unavailable",
                    }
                    status = 503
            raw = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(
        (config.get("bind", "127.0.0.1"), config["port"]), Handler
    )
    server.daemon_threads = True
    try:
        server.serve_forever()
    finally:
        server.server_close()
        lease.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    os.umask(0o077)
    serve(p.parse_args().config)
