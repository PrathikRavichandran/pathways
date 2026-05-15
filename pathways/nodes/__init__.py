"""LangGraph nodes for the Pathways state machine.

Each node is a pure-ish function: takes a PathwaysState, returns a partial
dict that LangGraph merges back into state. Side-effecting work (model
calls, MCP calls) happens inside nodes; the graph itself is just routing.
"""
