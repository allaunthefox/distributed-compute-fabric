"""LUPINE CUDA opcode constants and JSON argument schemas.

LUPINE Opcode Map — maps integer opcodes to CUDA/NVML API calls.
These are the operations that libcuda.so.1 preload shim can forward
over the VCN transport to a remote NVIDIA GPU.

All values are UInt32LE. Request/response payloads are JSON text.

Schema: vcn_lupine_opcodes_v1
"""

from typing import TypedDict


OPCODE_CUDA_MALLOC            = 1
OPCODE_CUDA_FREE              = 2
OPCODE_CUDA_MEMCPY            = 3
OPCODE_CUDA_MEMCPY_ASYNC      = 4
OPCODE_CUBLAS_CREATE          = 5
OPCODE_CUBLAS_DESTROY         = 6
OPCODE_CUBLAS_GEMM            = 7
OPCODE_CUBLAS_GEMV            = 8
OPCODE_CUDNN_CREATE           = 9
OPCODE_CUDNN_DESTROY          = 10
OPCODE_CUDNN_CONV_FWD         = 11
OPCODE_CUDNN_ACTIVATION_FWD  = 12
OPCODE_CUSOLVER_CREATE        = 13
OPCODE_CUSOLVER_DESTROY       = 14
OPCODE_CUSOLVER_ORGQR         = 15
OPCODE_CUSOLVER_GETRF         = 16
OPCODE_NVML_INIT              = 17
OPCODE_NVML_DEVICE_GET_COUNT  = 18
OPCODE_NVML_DEVICE_GET_NAME  = 19
OPCODE_NVML_DEVICE_GET_HANDLE = 20
OPCODE_NVML_DEVICE_GET_UTIL   = 21
OPCODE_NVML_DEVICE_GET_MEM    = 22

OPCODE_NAMES = {
    OPCODE_CUDA_MALLOC:            "cudaMalloc",
    OPCODE_CUDA_FREE:              "cudaFree",
    OPCODE_CUDA_MEMCPY:            "cudaMemcpy",
    OPCODE_CUDA_MEMCPY_ASYNC:      "cudaMemcpyAsync",
    OPCODE_CUBLAS_CREATE:          "cuBLAScreate",
    OPCODE_CUBLAS_DESTROY:         "cuBLASdestroy",
    OPCODE_CUBLAS_GEMM:            "cuBLASgemm",
    OPCODE_CUBLAS_GEMV:            "cuBLASgemv",
    OPCODE_CUDNN_CREATE:           "cuDNNcreate",
    OPCODE_CUDNN_DESTROY:          "cuDNNdestroy",
    OPCODE_CUDNN_CONV_FWD:         "cuDNNconvolutionForward",
    OPCODE_CUDNN_ACTIVATION_FWD:   "cuDNNactivationForward",
    OPCODE_CUSOLVER_CREATE:        "cuSOLVERcreate",
    OPCODE_CUSOLVER_DESTROY:       "cuSOLVERdestroy",
    OPCODE_CUSOLVER_ORGQR:         "cuSOLVERdnorgqr",
    OPCODE_CUSOLVER_GETRF:         "cuSOLVERgetrf",
    OPCODE_NVML_INIT:              "nvmlInit",
    OPCODE_NVML_DEVICE_GET_COUNT:  "nvmlDeviceGetCount",
    OPCODE_NVML_DEVICE_GET_NAME:   "nvmlDeviceGetName",
    OPCODE_NVML_DEVICE_GET_HANDLE: "nvmlDeviceGetHandleByIndex",
    OPCODE_NVML_DEVICE_GET_UTIL:   "nvmlDeviceGetUtilizationRates",
    OPCODE_NVML_DEVICE_GET_MEM:    "nvmlDeviceGetMemoryInfo",
}

CUDA_MEMCPY_KIND_HOST_TO_DEVICE = 1
CUDA_MEMCPY_KIND_DEVICE_TO_HOST = 2
CUDA_MEMCPY_KIND_DEVICE_TO_DEVICE = 3
CUDA_MEMCPY_KIND_DEFAULT = 0


class CudaMallocArgs(TypedDict):
    ptr: int
    size: int


class CudaFreeArgs(TypedDict):
    ptr: int


class CudaMemcpyArgs(TypedDict):
    dst: int
    src: int
    bytes: int
    kind: int


class CuBLASGemmArgs(TypedDict):
    handle: int
    transA: int
    transB: int
    m: int
    n: int
    k: int
    alpha: float
    A: int
    lda: int
    B: int
    ldb: int
    beta: float
    C: int
    ldc: int


class CuBLASGemvArgs(TypedDict):
    handle: int
    trans: int
    m: int
    n: int
    alpha: float
    A: int
    lda: int
    x: int
    incx: int
    beta: float
    y: int
    incy: int


class CuDNNConvFwdArgs(TypedDict):
    handle: int
    x_desc: int
    x: int
    w_desc: int
    w: int
    conv_desc: int
    algo: int
    workspace: int
    workSize: int
    y_desc: int
    y: int


class CuSOLVEROrgqrArgs(TypedDict):
    handle: int
    A: int
    lda: int
    n: int
    tau: int


class NvmlDeviceGetNameArgs(TypedDict):
    index: int


class NvmlDeviceGetHandleArgs(TypedDict):
    index: int


LUPINE_OPCODES = frozenset(OPCODE_NAMES.keys())
