"""
Message Cleaner — filter pseudo-requests, deduplicate, truncate long messages.

Default: disabled. Enable via config: {"agent": {"cleaner": {"enabled": true}}}
"""

import hashlib
import logging
import re
from typing import Optional, List, Dict

logger = logging.getLogger("tabbit2agent.cleaner")

# ── Pseudo-request patterns ──

PSEUDO_REQUEST_PATTERNS = [
    # Title generation (WorkBuddy, Trae, CodeBuddy)
    r"(?i)generate\s+a\s+concise.*?title",
    r"(?i)sentence-case\s+title",
    r"(?i)Respond\s+with\s+EXACTLY\s+one\s+JSON\s+object.*?isNewTopic",
    # Summarization
    r"(?i)summarize\s+the\s+above\s+into\s+one\s+sentence",
    r"(?i)summarize\s+this\s+conversation",
    # Reflection
    r"(?i)please\s+reflect\s+on\s+the\s+previous\s+response",
    r"(?i)review\s+your\s+last\s+answer",
    # Trae Solo pre-instruction
    r"/ask\b",
    # CRITICAL CONSTRAINTS block (title generation metadata)
    r"(?i)CRITICAL\s+CONSTRAINTS.*?EXACTLY\s+one\s+JSON\s+object",
    r"(?i)You\s+are\s+NOT\s+a\s+code\s+generator.*?only\s+summarize\s+its\s+intent",
]

# ── Content hash cache for dedup ──
_hash_cache: Dict[str, set] = {}


def _content_hash(text: str) -> str:
    """Stable hash for message content dedup."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def is_pseudo_request(system_content: str) -> bool:
    """Check if a system message is a pseudo-request (title gen, summary, reflection)."""
    for pattern in PSEUDO_REQUEST_PATTERNS:
        if re.search(pattern, system_content):
            return True
    return False


def clean_system_messages(messages: List[dict], dedup_session: str = "") -> List[dict]:
    """Filter out pseudo-request system messages. Optionally deduplicate by content hash.

    Args:
        messages: list of {"role": str, "content": str} dicts
        dedup_session: session key for dedup tracking (empty = no dedup)

    Returns:
        filtered messages list
    """
    cleaned = []
    seen_hashes = _hash_cache.get(dedup_session, set())

    for msg in messages:
        role = msg.get("role", "")
        content = str(msg.get("content", ""))

        if role == "system":
            if is_pseudo_request(content):
                logger.info(f"[cleaner] filtered pseudo-request system msg: {content[:80]}...")
                continue
            # Skip large agent system prompts (>2000 chars)
            if len(content) > 2000:
                logger.info(f"[cleaner] skipped agent system prompt ({len(content)} chars)")
                continue

        # Dedup by content hash (only for system/tool messages, NOT user messages)
        if dedup_session and role in ("system", "tool"):
            h = _content_hash(content)
            if h in seen_hashes:
                logger.info(f"[cleaner] dedup skipped duplicate {role} msg hash={h}")
                continue
            seen_hashes.add(h)

        cleaned.append(msg)

    if dedup_session:
        _hash_cache[dedup_session] = seen_hashes
        # Limit cache size
        if len(seen_hashes) > 500:
            _hash_cache[dedup_session] = set(list(seen_hashes)[-200:])

    return cleaned


def extract_user_query(user_content: str) -> str:
    """Extract the real user question from a WorkBuddy-style huge message.

    Strategy (in order):
    1. <user_query> tag extraction
    2. Reverse-scan for meaningful short lines (skip OS/Shell/Workspace env info)
    3. Last 500 chars fallback
    """
    if not user_content:
        return ""

    # 1) <user_query> tag
    match = re.search(r"<user_query>(.*?)</user_query>", user_content, re.DOTALL)
    if match:
        return match.group(1).strip()

    if len(user_content) < 2000:
        return user_content

    # 2) Reverse-scan for meaningful lines
    lines = user_content.strip().split("\n")
    meaningful = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        if len(line) > 200:
            continue
        if line.startswith((
            "OS Version:", "Shell:", "Workspace:", "Current date:",
            "<system-reminder", "</system-reminder>", "```", "<!--",
        )):
            continue
        meaningful.insert(0, line)
        if len("\n".join(meaningful)) > 500:
            break

    return "\n".join(meaningful) if meaningful else user_content[-500:]


def build_agent_content(messages: List[dict], dedup_session: str = "") -> str:
    """Build the content string to send to Tabbit, with cleaning applied.

    - System: only user-defined short prompts (skip agent metadata)
    - User: extract real question from huge WorkBuddy messages
    - Tool: pass through unchanged
    - Assistant: skip (Tabbit room maintains history)

    Returns: content string ready for Tabbit API.
    """
    cleaned = clean_system_messages(messages, dedup_session)

    system_parts = []
    last_user = ""

    for msg in cleaned:
        role = msg.get("role", "")
        content = str(msg.get("content", ""))

        if role == "system":
            system_parts.append(content)
        elif role == "user":
            last_user = extract_user_query(content)
        elif role == "tool":
            # Tool results: prepend as context
            tool_name = msg.get("name", msg.get("tool_call_name", "tool"))
            system_parts.append(f"[Tool Result - {tool_name}]: {content[:2000]}")
        # assistant messages are skipped — Tabbit room has the history

    if system_parts:
        return "\n\n".join(system_parts) + "\n\n" + last_user
    return last_user


def clear_dedup_cache(session_key: Optional[str] = None):
    """Clear dedup hash cache for a session or all sessions."""
    if session_key:
        _hash_cache.pop(session_key, None)
    else:
        _hash_cache.clear()
