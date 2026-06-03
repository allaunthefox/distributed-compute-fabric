#!/bin/sh
# Fix SSH key permissions (k8s secret mounts may not preserve mode)
if [ -f /identity/id_ed25519 ]; then
    cp /identity/id_ed25519 /root/.ssh/id_ed25519
    chmod 600 /root/.ssh/id_ed25519
fi
exec uvicorn main:app --host 0.0.0.0 --port 8787 --workers 1
