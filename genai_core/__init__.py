"""Compatibility shim for the workshop's shared GenAI bootstrap API.

This allows the app code to keep importing ``from genai_core import
bootstrap_local_genai`` without rewriting the graph layer.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from local_genai import bootstrap_local_genai

__all__ = ["bootstrap_local_genai"]
