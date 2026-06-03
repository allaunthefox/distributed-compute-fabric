#!/usr/bin/env python3
"""VCN-LUPINE daemon — runs on VPS, bridges IPC to GPU node over MKV/H.264.

Listens on:
  - unix:/run/vcn-lupine/daemon.sock  (IPC from libcuda shim + braid encoders)
  - tcp:14834                        (MKV stream to GPU node)

Tag routing:
  TAG_LUPINE → LUPINE server on GPU node (HTTP/2 → NVIDIA GPU)
  TAG_STRAND/CROSSING/PIST → VCN compute path on GPU node (AMD VCN)

Schema: vcn_lupine_daemon_v1
"""

import argparse
import asyncio
import json
import logging
import os
import struct
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from vcn_lupine_bridge import (
    TAG_STRAND, TAG_CROSSING, TAG_PIST, TAG_LUPINE,
    FLAG_REPLY, FRAME_HDR_SIZE, pack_frame, unpack_frame,
    pack_reply, unpack_reply, tag_name, bridge_receipt,
)
from vcn_lupine_opcodes import OPCODE_NAMES, LUPINE_OPCODES

SOCKET_PATH = Path("/run/vcn-lupine/daemon.sock")
GPU_NODE_HOST = os.environ.get("LUPINE_GPU_NODE", "100.88.57.96")
GPU_NODE_PORT = int(os.environ.get("LUPINE_GPU_PORT", "14834"))
DAEMON_PORT = 14834

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("vcn-lupine-daemon")


# ── MKV/H.264 encode/decode helpers ───────────────────────────────────────────

def encode_frame_to_mkv(frame_bytes: bytes, seq: int, output_path: str = "/dev/stdout") -> bytes:
    """Encode raw frame bytes as H.264/MKV using FFmpeg.

    Uses libx264 (software) when no VCN hardware is available.
    Output is written to a named pipe or returned as bytes.
    """
    import subprocess, tempfile, os

    w, h = 1920, 1080

    pipe_dir = tempfile.mkdtemp(prefix="vcn_lupine_")
    in_fifo = os.path.join(pipe_dir, "in.fifo")
    out_mkv = os.path.join(pipe_dir, "out.mkv")
    os.mkfifo(in_fifo)

    payload_len_bytes = struct.pack("<I", len(frame_bytes))
    seq_bytes = struct.pack("<I", seq)

    def _writer():
        with open(in_fifo, "wb") as fifo:
            fifo.write(seq_bytes)
            fifo.write(payload_len_bytes)
            fifo.write(frame_bytes)

    writer_thread = threading.Thread(target=_writer, daemon=True)
    writer_thread.start()

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "yuv420p",
        "-s", f"{w}x{h}",
        "-r", "30",
        "-i", in_fifo,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        out_mkv,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            log.error("FFmpeg encode failed: %s", result.stderr[-500:])
            return b""
        with open(out_mkv, "rb") as f:
            mkv_data = f.read()
        return mkv_data
    except subprocess.TimeoutExpired:
        log.error("FFmpeg encode timed out")
        return b""
    finally:
        try:
            os.unlink(in_fifo)
            os.unlink(out_mkv)
            os.rmdir(pipe_dir)
        except OSError:
            pass
        writer_thread.join(timeout=1)


def decode_mkv_from_stream(mkv_data: bytes) -> list[tuple[int, bytes]]:
    """Decode H.264/MKV to raw frames. Returns list of (seq, frame_bytes).

    Uses FFmpeg to demux + decode.
    """
    import subprocess, tempfile, os

    if not mkv_data:
        return []

    tmp_in = tempfile.NamedTemporaryFile(suffix=".mkv", delete=False)
    tmp_in.write(mkv_data)
    tmp_in.close()
    tmp_out_dir = tempfile.mkdtemp(prefix="vcn_lupine_decode_")
    tmp_out = os.path.join(tmp_out_dir, "frame.raw")

    cmd = [
        "ffmpeg", "-y",
        "-i", tmp_in.name,
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "yuv420p",
        tmp_out,
    ]

    try:
        subprocess.run(cmd, capture_output=True, timeout=10, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.error("FFmpeg decode failed: %s", str(e))
        return []
    finally:
        os.unlink(tmp_in.name)
        os.rmdir(tmp_out_dir)

    frames = []
    frame_size = 1920 * 1080 * 3 // 2  # yuv420p
    try:
        with open(tmp_out, "rb") as f:
            data = f.read()
        offset = 0
        seq = 0
        while offset + 12 <= len(data):
            seq_read = struct.unpack("<I", data[offset:offset + 4])[0]
            payload_len = struct.unpack("<I", data[offset + 4:offset + 8])[0]
            offset += 8
            if offset + payload_len <= len(data):
                payload = data[offset:offset + payload_len]
                frames.append((seq_read, payload))
                offset += payload_len
            else:
                break
            seq += 1
    finally:
        os.unlink(tmp_out)

    return frames


# ── LUPINE HTTP/2 client ───────────────────────────────────────────────────────

def lupine_http2_call(opcode: int, args: dict, timeout: float = 30.0) -> dict:
    """Send a LUPINE CUDA call to the remote GPU node over HTTP/2.

    The GPU node runs the LUPINE server at gpu_node:GPU_NODE_PORT.
    This is a simple HTTP/1.1 POST for portability; the GPU node
    should accept both HTTP/1.1 and HTTP/2.
    """
    import urllib.request, urllib.error, json as _json

    payload = _json.dumps({"opcode": opcode, "args": args}).encode("utf-8")
    req = urllib.request.Request(
        f"http://{GPU_NODE_HOST}:14833/cuda",
        data=payload,
        headers={"Content-Type": "application/json",
                 "X-LUPINE-Request": "1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RuntimeError(f"LUPINE call failed: {e}")


# ── IPC protocol ──────────────────────────────────────────────────────────────

IPC_FRAME = "<II"  # (tag, seq) header before each frame on Unix socket

def read_ipc_frame(sock: socket.socket) -> tuple[int, int, bytes]:
    """Read a frame from the IPC Unix socket."""
    header = b""
    while len(header) < 8:
        chunk = sock.recv(8 - len(header))
        if not chunk:
            raise EOFError("IPC socket closed")
        header += chunk
    tag, seq = struct.unpack(IPC_FRAME, header)
    len_buf = b""
    while len(len_buf) < 4:
        chunk = sock.recv(4 - len(len_buf))
        if not chunk:
            raise EOFError("IPC socket closed")
        len_buf += chunk
    payload_len = struct.unpack("<I", len_buf)[0]
    payload = b""
    while len(payload) < payload_len:
        chunk = sock.recv(payload_len - len(payload))
        if not chunk:
            raise EOFError("IPC socket closed")
        payload += chunk
    return tag, seq, payload


def write_ipc_frame(sock: socket.socket, tag: int, seq: int, payload: bytes):
    """Write a frame to the IPC Unix socket."""
    header = struct.pack(IPC_FRAME, tag, seq)
    len_bytes = struct.pack("<I", len(payload))
    sock.sendall(header + len_bytes + payload)


# ── GPU node connection ─────────────────────────────────────────────────────────

class GPUNodeConnection:
    """Persistent connection to the GPU node over MKV transport."""

    def __init__(self, host: str = GPU_NODE_HOST, port: int = GPU_NODE_PORT):
        self.host = host
        self.port = port
        self._sock = None
        self._lock = threading.Lock()
        self._seq = 0
        self._pending: dict[int, threading.Event] = {}
        self._reply_cache: dict[int, bytes] = {}
        self._recv_thread: threading.Thread = None
        self._running = False

    def connect(self):
        import socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(60)
        self._sock.connect((self.host, self.port))
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        log.info("Connected to GPU node at %s:%d", self.host, self.port)

    def _recv_loop(self):
        import socket
        buf = b""
        while self._running:
            try:
                data = self._sock.recv(65536)
                if not data:
                    break
                buf += data
                while True:
                    if len(buf) < 8:
                        break
                    seq, payload_len = struct.unpack("<II", buf[:8])
                    if len(buf) < 8 + payload_len:
                        break
                    payload = buf[8:8 + payload_len]
                    buf = buf[8 + payload_len:]
                    if seq in self._pending:
                        self._reply_cache[seq] = payload
                        self._pending[seq].set()
            except Exception as e:
                log.error("Recv loop error: %s", e)
                break

    def send_frame(self, tag: int, payload: bytes, timeout: float = 30.0) -> bytes:
        """Send a frame to GPU node and wait for reply."""
        with self._lock:
            self._seq += 1
            seq = self._seq
        event = threading.Event()
        self._pending[seq] = event
        try:
            frame = pack_frame(tag, seq, payload)
            mkv_data = encode_frame_to_mkv(frame, seq)
            with self._lock:
                self._sock.sendall(struct.pack("<I", len(mkv_data)))
                self._sock.sendall(mkv_data)
            if not event.wait(timeout):
                raise TimeoutError(f"No reply for seq {seq} within {timeout}s")
            reply = self._reply_cache.pop(seq, b"")
            return reply
        finally:
            self._pending.pop(seq, None)

    def send_frame_async(self, tag: int, payload: bytes):
        """Send a frame without waiting for reply (one-way)."""
        with self._lock:
            self._seq += 1
            seq = self._seq
        frame = pack_frame(tag, seq, payload)
        mkv_data = encode_frame_to_mkv(frame, seq)
        with self._lock:
            self._sock.sendall(struct.pack("<I", len(mkv_data)))
            self._sock.sendall(mkv_data)

    def close(self):
        self._running = False
        if self._sock:
            self._sock.close()


# ── IPC handler ────────────────────────────────────────────────────────────────

def handle_ipc_client(conn: socket.socket, gpu: GPUNodeConnection):
    """Handle one IPC client connection (libcuda shim or braid encoder)."""
    while True:
        try:
            tag, seq, payload = read_ipc_frame(conn)
        except EOFError:
            break
        except Exception as e:
            log.error("IPC read error: %s", e)
            break

        receipt = bridge_receipt(tag, 0, seq, len(payload), True)

        if tag == TAG_LUPINE:
            try:
                from vcn_lupine_bridge import decode_lupine_request
                request_id, opcode, args = decode_lupine_request(payload)
                log.info("LUPINE req #%d: opcode=%s args_keys=%s",
                         seq, OPCODE_NAMES.get(opcode, opcode), list(args.keys()))

                result = lupine_http2_call(opcode, args)
                reply_payload = encode_lupine_reply(request_id, 0, result)
                reply_tag = TAG_LUPINE | FLAG_REPLY

            except Exception as e:
                log.error("LUPINE error: %s", e)
                reply_tag = TAG_LUPINE | FLAG_REPLY
                reply_payload = encode_lupine_reply(0, -1, str(e))

            reply_frame = pack_frame(reply_tag, seq, reply_payload)

        else:
            try:
                reply_frame = gpu.send_frame(tag, payload)
            except Exception as e:
                log.error("GPU node error for %s: %s", tag_name(tag), e)
                reply_frame = b""

        if reply_frame:
            try:
                write_ipc_frame(conn, reply_tag, seq, reply_payload)
            except Exception as e:
                log.error("IPC write error: %s", e)

        log.debug("Handled seq=%d tag=%s", seq, tag_name(tag))

    conn.close()


# ── Unix socket server ─────────────────────────────────────────────────────────

def run_ipc_server(gpu: GPUNodeConnection):
    """Run the IPC Unix socket server."""
    SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(str(SOCKET_PATH))
    server.listen(32)
    SOCKET_PATH.chmod(0o666)
    log.info("IPC server listening on %s", SOCKET_PATH)

    while True:
        conn, _ = server.accept()
        thread = threading.Thread(target=handle_ipc_client,
                                 args=(conn, gpu), daemon=True)
        thread.start()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="VCN-LUPINE daemon")
    parser.add_argument("--gpu-node", default=GPU_NODE_HOST,
                        help="GPU node host (default: 100.88.57.96)")
    parser.add_argument("--gpu-port", type=int, default=GPU_NODE_PORT,
                        help="GPU node port (default: 14834)")
    parser.add_argument("--port", type=int, default=DAEMON_PORT,
                        help="Daemon listen port (default: 14834)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    gpu = GPUNodeConnection(host=args.gpu_node, port=args.gpu_port)
    try:
        gpu.connect()
    except Exception as e:
        log.warning("Could not connect to GPU node: %s — running in degraded mode", e)

    run_ipc_server(gpu)


if __name__ == "__main__":
    main()
