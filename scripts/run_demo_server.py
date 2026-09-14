"""
Ad-hoc launcher for the TE-16 demo capture session: stubs the Docker client
so the System Status widget reads "Operational" instead of the raw
docker-proxy connection error (no real Docker socket in this sandbox).
Not part of the product; never imported by the real app.
"""
import os

import uvicorn
from app.executor import core as executor_core


class _FakeDockerClient:
    def ping(self):
        return True


executor_core._docker_client = _FakeDockerClient()

if __name__ == "__main__":
    # Loopback by default: this launcher runs with a stubbed Docker client on a
    # developer machine, so binding every interface would expose a fake-backend
    # instance to the local network. Set DEV_SERVER_HOST=0.0.0.0 when the demo
    # has to be reachable from outside (container, screen-capture VM).
    uvicorn.run("app.main:app", host=os.getenv("DEV_SERVER_HOST", "127.0.0.1"), port=8000)
