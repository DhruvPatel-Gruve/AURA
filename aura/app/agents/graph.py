"""LangGraph StateGraph — AURA agent pipeline.

Entry point: compiled_graph
  compiled_graph.ainvoke(state)  → final AgentState
  compiled_graph.astream(state)  → async generator of (node_name, partial_state)

Graph topology:
  kill_switch → priority_scorer → triage → assignment →
  collision → autonomy → sla → abstention → resolution → confidence_gate → audit_finalizer

Conditional edges halt to audit_finalizer when pipeline_halted=True.
"""

from langgraph.graph import END, StateGraph

from app.models.agent_state import AgentState
from app.agents.nodes.kill_switch_node import kill_switch_node
from app.agents.nodes.priority_scorer_node import priority_scorer_node
from app.agents.nodes.triage_node import triage_node
from app.agents.nodes.assignment_node import assignment_node
from app.agents.nodes.collision_node import collision_node
from app.agents.nodes.autonomy_node import autonomy_node
from app.agents.nodes.sla_node import sla_node
from app.agents.nodes.abstention_node import abstention_node
from app.agents.nodes.resolution_node import resolution_node
from app.agents.nodes.confidence_gate_node import confidence_gate_node
from app.agents.nodes.audit_finalizer_node import audit_finalizer_node

# ── Router helpers ────────────────────────────────────────────────────────────

def _route_on_halt(state: AgentState) -> str:
    """Generic router: 'halt' if pipeline_halted else 'continue'."""
    return "halt" if state.get("pipeline_halted") else "continue"


# ── Build graph ───────────────────────────────────────────────────────────────

_builder = StateGraph(AgentState)

_builder.add_node("kill_switch_node", kill_switch_node)
_builder.add_node("priority_scorer_node", priority_scorer_node)
_builder.add_node("triage_node", triage_node)
_builder.add_node("assignment_node", assignment_node)
_builder.add_node("collision_node", collision_node)
_builder.add_node("autonomy_node", autonomy_node)
_builder.add_node("sla_node", sla_node)
_builder.add_node("abstention_node", abstention_node)
_builder.add_node("resolution_node", resolution_node)
_builder.add_node("confidence_gate_node", confidence_gate_node)
_builder.add_node("audit_finalizer_node", audit_finalizer_node)

_builder.set_entry_point("kill_switch_node")

_HALT_TARGET = "audit_finalizer_node"

_builder.add_conditional_edges(
    "kill_switch_node",
    _route_on_halt,
    {"halt": _HALT_TARGET, "continue": "priority_scorer_node"},
)
_builder.add_edge("priority_scorer_node", "triage_node")
_builder.add_edge("triage_node", "assignment_node")
_builder.add_edge("assignment_node", "collision_node")
_builder.add_edge("collision_node", "autonomy_node")
_builder.add_conditional_edges(
    "autonomy_node",
    _route_on_halt,
    {"halt": _HALT_TARGET, "continue": "sla_node"},
)
_builder.add_edge("sla_node", "abstention_node")
_builder.add_conditional_edges(
    "abstention_node",
    _route_on_halt,
    {"halt": _HALT_TARGET, "continue": "resolution_node"},
)
_builder.add_edge("resolution_node", "confidence_gate_node")
_builder.add_edge("confidence_gate_node", _HALT_TARGET)
_builder.add_edge(_HALT_TARGET, END)

compiled_graph = _builder.compile()
