"""LangGraph ReAct agent builder wired to the shared Local GenAI model.

An ``assistant`` (model) node and a ``tools`` node wired into a ReAct loop,
capped at ``MAX_STEPS`` tool-calling turns. Temperature is fixed at 0 so runs are
deterministic and results are reproducible.

The model is cached once (it is expensive to construct); the agent itself is
rebuilt every time the toolbox changes, because in this workshop the *tools* are
the variable, not the prompt.
"""

import streamlit as st

from config import MAX_STEPS
from agent.prompts import AGENT_PROMPT


@st.cache_resource(show_spinner=False)
def get_llm():
    """Construct the Local GenAI chat model once (deterministic, temp 0)."""
    from genai_core import bootstrap_local_genai

    return bootstrap_local_genai(temperature=0, max_completion_tokens=800)


def build_agent(tools):
    """Compile a ReAct agent over ``tools`` using the fixed system prompt."""
    from langchain_core.messages import SystemMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode, tools_condition

    llm = get_llm()
    llm_with_tools = llm.bind_tools(tools) if tools else llm

    class AgentState(MessagesState):
        steps: int

    def call_model(state: AgentState):
        steps = state.get("steps", 0)
        if steps >= MAX_STEPS:
            response = llm.invoke([
                SystemMessage(content="Tool call limit reached. Give your best answer now."),
                *state["messages"],
            ])
        else:
            response = llm_with_tools.invoke([
                SystemMessage(content=AGENT_PROMPT),
                *state["messages"],
            ])
        return {"messages": [response], "steps": steps + 1}

    agent_builder = StateGraph(AgentState)
    agent_builder.add_node("assistant", call_model)
    agent_builder.add_node("tools", ToolNode(tools))
    agent_builder.add_edge(START, "assistant")
    agent_builder.add_conditional_edges(
        "assistant", tools_condition, {"tools": "tools", "__end__": END}
    )
    agent_builder.add_edge("tools", "assistant")
    return agent_builder.compile()
