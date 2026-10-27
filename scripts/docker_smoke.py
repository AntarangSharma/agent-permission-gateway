"""Verify the built image with the same smoke function used for a native checkout."""

import subprocess

from smoke import smoke

container_id = subprocess.check_output(
    ["docker", "run", "-d", "--rm", "-p", "127.0.0.1::8000", "agent-permission-gateway:local"],
    text=True,
).strip()
try:
    port = (
        subprocess.check_output(["docker", "port", container_id, "8000"], text=True)
        .strip()
        .split(":")[-1]
    )
    smoke("http://127.0.0.1:" + port)
finally:
    subprocess.run(["docker", "stop", container_id], check=True, stdout=subprocess.DEVNULL)
