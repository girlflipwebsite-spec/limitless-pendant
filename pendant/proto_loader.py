"""Import wrapper for the generated protobuf module.

Regenerate proto/pendant_pb2.py after editing proto/pendant.proto with:
    python -m grpc_tools.protoc -I proto --python_out=proto proto/pendant.proto
"""

import sys
from pathlib import Path

_proto_dir = Path(__file__).resolve().parent.parent / "proto"
if str(_proto_dir) not in sys.path:
    sys.path.insert(0, str(_proto_dir))

try:
    import pendant_pb2 as pb
    PROTOBUF_AVAILABLE = True
except ImportError:
    pb = None  # type: ignore
    PROTOBUF_AVAILABLE = False

__all__ = ["pb", "PROTOBUF_AVAILABLE"]
