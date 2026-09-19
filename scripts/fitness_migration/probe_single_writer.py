#!/usr/bin/env python3
"""Synthetic feasibility test, NOT the production memory service.

A token-gated temporary HTTP writer serializes host/container requests into one
Markdown file. Tests transport and exclusion only, not journal transaction parity.
"""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import urllib.error
import urllib.request


def run(image, directory):
    directory = directory.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    token = secrets.token_hex(32)
    state, lock = {}, threading.Lock()
    path = directory / "synthetic.md"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != "/capture" or not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + token
            ):
                self.send_error(403)
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                self.send_error(400)
                return
            try:
                data = json.loads(self.rfile.read(length))
                if set(data) != {"id", "text"} or not all(
                    type(v) is str for v in data.values()
                ):
                    raise ValueError()
            except (ValueError, TypeError):
                self.send_error(400)
                return
            with lock:
                if data["id"] in state and state[data["id"]] != data["text"]:
                    self.send_error(409)
                    return
                updated = {**state, data["id"]: data["text"]}
                tmp = directory / "pending"
                with tmp.open("w") as f:
                    f.write(
                        "# Synthetic writer probe\n\n"
                        + json.dumps(updated, sort_keys=True)
                        + "\n"
                    )
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
                state.update(updated)
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def host_capture(i):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/capture",
            data=json.dumps(
                {"id": f"host-{i % 20}", "text": f"synthetic-{i % 20}"}
            ).encode(),
            headers={"Authorization": "Bearer " + token},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status

    code = """import os,json,urllib.request
from concurrent.futures import ThreadPoolExecutor
def send(i):
 req=urllib.request.Request(os.environ['PROBE_URL'],data=json.dumps({'id':f'container-{i%20}','text':f'synthetic-{i%20}'}).encode(),headers={'Authorization':'Bearer '+os.environ['PROBE_TOKEN']},method='POST')
 with urllib.request.urlopen(req,timeout=10) as r:return r.status
with ThreadPoolExecutor(max_workers=4) as pool:
 assert list(pool.map(send,range(40))) == [204]*40
"""
    try:
        denied = False
        try:
            urllib.request.urlopen(
                urllib.request.Request(f"http://127.0.0.1:{port}/capture", data=b"{}"),
                timeout=5,
            )
        except urllib.error.HTTPError as exc:
            denied = exc.code == 403
        env = {
            **os.environ,
            "PROBE_TOKEN": token,
            "PROBE_URL": f"http://host.docker.internal:{port}/capture",
        }
        with ThreadPoolExecutor(max_workers=5) as pool:
            container = pool.submit(
                subprocess.run,
                [
                    "docker",
                    "run",
                    "--rm",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--env",
                    "PROBE_TOKEN",
                    "--env",
                    "PROBE_URL",
                    "--entrypoint",
                    "python",
                    image,
                    "-c",
                    code,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=45,
            )
            statuses = list(pool.map(host_capture, range(40)))
            result = container.result()
        persisted = json.loads(path.read_text().split("\n\n", 1)[1])
        expected = {
            f"{origin}-{i}": f"synthetic-{i}"
            for origin in ("host", "container")
            for i in range(20)
        }
        report = {
            "checks": {
                "unauthenticated_refused": denied,
                "host_requests_succeeded": statuses == [204] * 40,
                "container_requests_succeeded": result.returncode == 0,
                "all_unique_captures_preserved": persisted == expected,
            },
            "scope": "synthetic transport/serialization only; not a production writer or crash recovery test",
        }
        report["passed"] = all(report["checks"].values())
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image", required=True)
    p.add_argument("--directory", type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    print(json.dumps(run(args.image, args.directory), indent=2))
