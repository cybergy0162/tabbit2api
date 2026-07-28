"""Agent-level enhancements for Tabbit2API.

Submodules:
- message_cleaner: filter pseudo-requests, dedup, truncate long messages
- context_manager: sliding window, summarization, token estimation
- tool_handler: function calling / tool use support
- agent_router: agent-aware model routing
- token_pool: enhanced token pool with weighted round-robin and state machine
"""
