#!/usr/bin/env python3
"""Test real host/container flock exclusion using an isolated synthetic bind mount."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

TRY = """import fcntl
with open('/probe/writer.lock','r+') as f:
 try:
  fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  print('acquired')
 except BlockingIOError:
  print('blocked')
"""
HOLD = """import fcntl,time
from pathlib import Path
with open('/probe/writer.lock','r+') as f:
 fcntl.flock(f,fcntl.LOCK_EX)
 Path('/probe/held').write_text('ready')
 time.sleep(25)
"""


def run(image, directory):
    directory = directory.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = directory / "writer.lock"
    path.touch(mode=0o600)
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--mount",
        f"type=bind,source={directory},target=/probe",
        "--entrypoint",
        "python",
        image,
        "-c",
    ]
    checks = {}
    observations = {}
    with path.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        proc = subprocess.run(
            command + [TRY], capture_output=True, text=True, timeout=45
        )
        observations["host_held_container_result"] = {
            "exit_code": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
        checks["host_excludes_container"] = (
            proc.returncode == 0 and proc.stdout.strip() == "blocked"
        )
    proc = subprocess.run(command + [TRY], capture_output=True, text=True, timeout=45)
    checks["released_host_allows_container"] = (
        proc.returncode == 0 and proc.stdout.strip() == "acquired"
    )
    # A bounded holder exits by itself even if this probing process dies.
    holder = subprocess.Popen(
        command + [HOLD], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 15
        while (
            not (directory / "held").exists()
            and holder.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.1)
        checks["container_holder_started"] = (directory / "held").exists()
        with path.open("r+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                checks["container_excludes_host"] = False
            except BlockingIOError:
                checks["container_excludes_host"] = checks["container_holder_started"]
        holder.wait(timeout=40)
    finally:
        if holder.poll() is None:
            holder.terminate()
            holder.wait(timeout=10)
    result = {
        "checks": checks,
        "observations": observations,
        "passed": all(checks.values()),
        "scope": "synthetic bind mount using deployed fitness image; not manual-editor coordination",
    }
    (directory / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image", required=True)
    p.add_argument("--directory", type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    print(json.dumps(run(args.image, args.directory), indent=2))
