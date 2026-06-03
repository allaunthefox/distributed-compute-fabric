FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt .
RUN pip install --no-cache-dir \
    -r requirements.txt \
    "ray[serve]>=2.9.0" \
    "llama-cpp-python>=0.2.0" \
    httpx

COPY app/orchestrator.py .

ENV PYTHONUNBUFFERED=1 \
    HERMES_PORT=8000 \
    ORCHESTRATOR_ENABLED=true

EXPOSE 8000

CMD ["uvicorn", "orchestrator:app", "--host", "0.0.0.0", "--port", "8000"]
