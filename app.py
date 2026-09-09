"""
Design-a-Good-Tool — Travel Planning Workshop (Streamlit)
Run from this folder with:
    streamlit run app.py

The premise: everything you need to plan a trip already exists in the data. The
skill is choosing the RIGHT tools to extract it. The agent's prompt is FIXED.
Participants TOGGLE tools on and off in the right-hand rack — reading each
description to decide which fits — then ask the agent questions on the left and
JUDGE the answer and its trace for themselves. No score, no checklist.

Two lessons are built into the tool catalog:
  (a) The model reasons with common sense about what it doesn't know, so a good
      tool's description must carry its scope and limits.
  (b) A good tool is modular and rightly scoped — the god tool and the
      over-bundled decoys break the moment a question doesn't fit their hidden
      assumptions; small composable tools keep working.
"""

import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import config

config.ensure_local_genai_importable()
config.configure_page()

from agent.graph import build_agent
from agent.tools import (
    CATALOG,
    GROUPS,
    BROKEN_ENABLED,
    build_toolbox,
    dataset_tables,
)
from agent.runner import run_task
from ui import layout, workshop
from ui.assets import load_coba_svg
from ui.styles import inject_styles

inject_styles()
COBA_SVG = load_coba_svg()

layout.render_backdrop()
layout.render_corner_logo(COBA_SVG)
layout.render_header(COBA_SVG)


# ---------------------------------------------------------------------------
# Split each default description into the editable text and the fixed example.
# ---------------------------------------------------------------------------
def _split_description(desc: str):
    """Return (main_description, example_line) split on the 'Example:' marker."""
    idx = desc.find("Example:")
    if idx == -1:
        return desc.strip(), ""
    return desc[:idx].strip(), desc[idx:].strip()


DEFAULT_MAIN = {t.id: _split_description(t.description)[0] for t in CATALOG}
EXAMPLES = {t.id: _split_description(t.description)[1] for t in CATALOG}


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "wk_init" not in st.session_state:
    for t in CATALOG:
        st.session_state[f"en_{t.id}"] = t.id in BROKEN_ENABLED
        st.session_state[f"desc_{t.id}"] = DEFAULT_MAIN[t.id]
    st.session_state.messages = []          # [{role, content, trace?}]
    st.session_state.wk_init = True


@st.dialog("Edit tool", width="large")
def _edit_tool_dialog(spec):
    """Blocking modal to edit the description the agent sees for one tool."""
    st.markdown(f"**`{spec.name}`** · {spec.group}")
    draft = st.text_area(
        "Description the agent sees",
        value=st.session_state[f"desc_{spec.id}"],
        key=f"draft_{spec.id}",
        height=220,
    )
    if EXAMPLES[spec.id]:
        st.markdown("**Example output**")
        st.code(EXAMPLES[spec.id], language="text")
    st.caption("This example is appended automatically — you only edit the "
               "description above.")
    if st.button("💾 Save changes", key=f"save_{spec.id}",
                 type="primary", use_container_width=True):
        st.session_state[f"desc_{spec.id}"] = draft
        st.rerun()


left, right = st.columns([1.15, 1], gap="large")


# ===========================================================================
# RIGHT: tools + data, on two tabs (rendered first so `enabled_ids` is known)
# ===========================================================================
with right:
    st.markdown('<div style="height:30px"></div>', unsafe_allow_html=True)
    tools_tab, data_tab = st.tabs(["Tools", "Data"])

    with tools_tab:
        rack = st.container(height=520, border=True, key="tool_rack")
        with rack:
            st.caption("Enable a tool with its checkbox. Click a tool's name to "
                       "edit the description the agent sees.")
            for group in GROUPS:
                st.markdown(f'<div class="wk-tool-group">{group}</div>',
                            unsafe_allow_html=True)
                for spec in [c for c in CATALOG if c.group == group]:
                    c_toggle, c_name = st.columns([0.12, 0.88])
                    with c_toggle:
                        st.checkbox("", key=f"en_{spec.id}",
                                    label_visibility="collapsed")
                    with c_name:
                        if st.button(f"✏️ `{spec.name}`", key=f"open_{spec.id}",
                                     use_container_width=True):
                            _edit_tool_dialog(spec)

    with data_tab:
        data_box = st.container(height=520, border=True, key="data_box")
        with data_box:
            for title, rows in dataset_tables().items():
                st.markdown(f'<div class="wk-tool-group">{title}</div>',
                            unsafe_allow_html=True)
                st.dataframe(rows, use_container_width=True, hide_index=True)

enabled_ids = {t.id for t in CATALOG if st.session_state[f"en_{t.id}"]}
tool_descriptions = {
    t.id: (st.session_state[f"desc_{t.id}"].strip()
           + ("\n" + EXAMPLES[t.id] if EXAMPLES[t.id] else "")).strip()
    for t in CATALOG
}


# ===========================================================================
# LEFT: chat
# ===========================================================================
with left:
    st.markdown('<div style="height:30px"></div>', unsafe_allow_html=True)

    chat_box = st.container(height=520, border=True, key="chat_box")
    with chat_box:
        if not st.session_state.messages:
            st.markdown(
                '<div class="trace-empty">Type a travel question below. '
                "The agent will use whatever tools you enabled — watch the "
                "trace to see what it actually called.</div>",
                unsafe_allow_html=True,
            )
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
                if m.get("trace"):
                    workshop.render_trace(m["trace"], open_by_default=False)

        # While a question is pending, show an animated "working" bubble
        # inside the chat window itself.
        if st.session_state.get("pending"):
            with st.chat_message("assistant"):
                st.markdown(
                    '<div class="agent-working">'
                    '<span class="agent-working-dots">'
                    '<span></span><span></span><span></span></span>'
                    '<span class="agent-working-text">The agent is working…</span>'
                    "</div>",
                    unsafe_allow_html=True,
                )

    user_text = st.chat_input("Ask your own travel question…")

    # Phase 1: capture the question, show it plus the working animation.
    if user_text:
        st.session_state.messages.append({"role": "user", "content": user_text})
        st.session_state.pending = user_text
        st.rerun()

    # Phase 2: a question is pending — compute the answer, then replace the
    # animation with the real assistant message.
    if st.session_state.get("pending"):
        pending_text = st.session_state.pending
        if not enabled_ids:
            answer = ("I have no tools enabled, so I can't look anything up. "
                      "Enable some tools in the rack on the right.")
            trace = []
        else:
            tools, meta = build_toolbox(enabled_ids, tool_descriptions)
            agent = build_agent(tools)
            result = run_task(agent, pending_text, meta)
            answer, trace = result.answer, result.trace
        st.session_state.messages.append(
            {"role": "assistant", "content": answer, "trace": trace}
        )
        st.session_state.pending = None
        st.rerun()
