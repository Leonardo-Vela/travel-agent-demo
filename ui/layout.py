"""Static page chrome for the workshop app: backdrop, corner logo and header."""

import streamlit as st


def render_backdrop() -> None:
    """Backdrop intentionally removed — the page background is plain white."""
    return


def render_corner_logo(coba_svg: str) -> None:
    """Render the small fixed logo in the upper-left corner."""
    st.markdown(f'<div class="corner-logo">{coba_svg}</div>', unsafe_allow_html=True)


def render_header(coba_svg: str) -> None:
    """Render the app header with logo and a simple static title."""
    st.markdown(f"""
    <div class="app-header">
        <div class="app-header-title">
            <div class="app-header-logo">{coba_svg}</div>
            <h1>Travel Agent</h1>
        </div>
    </div>
    """, unsafe_allow_html=True)
