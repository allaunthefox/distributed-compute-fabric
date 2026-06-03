# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi", "uvicorn"]
# ///
"""Registry API – worker node registration and heartbeat service."""

from fastapi import FastAPI

app = FastAPI(title="Registry API")


@app.get("/health")
def health():
    return {"status": "ok", "service": "registry"}


@app.post("/api/registry/join")
def join():
    return {"accepted": True, "node_id": "placeholder"}


@app.post("/api/registry/heartbeat")
def heartbeat():
    return {"ack": True}


@app.get("/api/registry/nodes")
def list_nodes():
    return {"nodes": []}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
