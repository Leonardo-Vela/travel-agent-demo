"""Small SVG avatars and logo loading for the workshop UI."""

import base64
from pathlib import Path

_COBA_SVG_PATH = Path(__file__).parent / "static" / "CB-2022-Ribbon_RGB.svg"


def load_coba_svg() -> str:
    """Load the CB-2022 ribbon SVG, stripping the XML/DOCTYPE header."""
    try:
        raw = _COBA_SVG_PATH.read_text(encoding="utf-8")
        idx = raw.find("<svg")
        return raw[idx:] if idx != -1 else raw
    except Exception:
        return (
            '<svg viewBox="0 0 116 100" xmlns="http://www.w3.org/2000/svg">'
            '<path d="M58 8 L108 53 L88 92 L28 92 L8 53 Z" fill="#E3A90B"/></svg>'
        )
