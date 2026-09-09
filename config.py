"""App configuration: paths, genai_core discovery, and page setup."""

from pathlib import Path

import streamlit as st

# streamlit_app_workshop/config.py -> project root is one level up
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
PAGE_TITLE = "Travel Agent"
PAGE_ICON = "A"

# Hard cap on the ReAct loop. Travel questions can chain several lookups (e.g.
# comparing all four cities, or flight + hotel + activity + a calculation), so
# the cap is generous enough for a well-chosen toolbox to finish while still
# stopping a runaway loop from hanging the room.
MAX_STEPS = 12


def ensure_local_genai_importable() -> None:
    """Verify the shared ``genai_core`` package is importable.

    ``genai_core`` is installed as an editable package in the project's virtual
    environment, so no path manipulation is required — we just surface a clear
    error if it is missing.
    """
    try:
        import genai_core  # noqa: F401
    except ImportError as exc:  # pragma: no cover - surfaced to the user
        raise ImportError(
            "Could not import the shared 'genai_core' package. Install it with "
            "`pip install -e genai_core` from the project root."
        ) from exc


def configure_page() -> None:
    """Apply the Streamlit page configuration (must run before other st calls)."""
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="wide",
    )
