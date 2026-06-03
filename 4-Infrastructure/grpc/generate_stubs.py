#!/usr/bin/env python3
"""
Generate Python gRPC stubs from proto definition.

Requirements:
    pip install grpcio-tools

Usage:
    python generate_stubs.py

Output:
    inference_pb2.py      - Message classes
    inference_pb2_grpc.py - Service stubs
"""

import os
from grpc_tools import protoc

PROTO_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = PROTO_DIR  # Output to same directory

protoc.main([
    "grpc_tools.protoc",
    f"--proto_path={PROTO_DIR}",
    f"--python_out={OUTPUT_DIR}",
    f"--grpc_python_out={OUTPUT_DIR}",
    os.path.join(PROTO_DIR, "inference.proto"),
])

print(f"Generated stubs in {OUTPUT_DIR}")
print("Files: inference_pb2.py, inference_pb2_grpc.py")
