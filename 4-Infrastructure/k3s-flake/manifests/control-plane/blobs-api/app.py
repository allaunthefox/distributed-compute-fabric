# /// script
# requires-python = ">=3.11"
# dependencies = ["fastapi", "uvicorn"]
# ///
"""Blobs API – binary object storage service."""

from fastapi import FastAPI

app = FastAPI(title="Blobs API")


@app.get("/health")
def health():
    return {"status": "ok", "service": "blobs"}


@app.put("/api/blobs/{key}")
def put_blob(key: str):
    return {"key": key, "stored": True}


@app.get("/api/blobs/{key}")
def get_blob(key: str):
    return {"key": key, "exists": False}


@app.get("/api/blobs/")
def list_blobs():
    return {"blobs": []}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
