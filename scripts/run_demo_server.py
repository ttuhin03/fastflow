"""
Ad-hoc launcher for the TE-16 demo capture session: stubs the Docker client
so the System Status widget reads "Operational" instead of the raw
docker-proxy connection error (no real Docker socket in this sandbox).
Not part of the product; never imported by the real app.
"""
import uvicorn
from app.executor import core as executor_core


class _FakeDockerClient:
    def ping(self):
        return True


executor_core._docker_client = _FakeDockerClient()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
