"""Tests for message_cleaner module."""
import sys
sys.path.insert(0, "/home/tabbit")

from core.agent.message_cleaner import (
    is_pseudo_request,
    clean_system_messages,
    extract_user_query,
    build_agent_content,
)


def test_is_pseudo_request_title_gen():
    """Title generation prompts should be detected."""
    assert is_pseudo_request("Generate a concise title for this conversation")
    assert is_pseudo_request("Generate a concise, sentence-case title (3-7 words)")
    assert is_pseudo_request("Respond with EXACTLY one JSON object: {\"isNewTopic\": true}")


def test_is_pseudo_request_summary():
    """Summary prompts should be detected."""
    assert is_pseudo_request("Summarize the above into one sentence")
    assert is_pseudo_request("Summarize this conversation")


def test_is_pseudo_request_reflection():
    """Reflection prompts should be detected."""
    assert is_pseudo_request("Please reflect on the previous response")
    assert is_pseudo_request("Review your last answer")


def test_is_pseudo_request_normal():
    """Normal system prompts should NOT be detected."""
    assert not is_pseudo_request("You are a helpful assistant")
    assert not is_pseudo_request("You are a professional security researcher")


def test_clean_system_messages_filters_pseudo():
    """System messages with pseudo-requests should be filtered out."""
    messages = [
        {"role": "system", "content": "Generate a concise title"},
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": "hi"},
    ]
    cleaned = clean_system_messages(messages)
    assert len(cleaned) == 2
    assert cleaned[0]["content"] == "You are a helpful assistant"


def test_clean_system_messages_skips_large():
    """Large agent system prompts (>2000 chars) should be skipped."""
    messages = [
        {"role": "system", "content": "A" * 3000},
        {"role": "user", "content": "hi"},
    ]
    cleaned = clean_system_messages(messages)
    assert len(cleaned) == 1
    assert cleaned[0]["role"] == "user"


def test_extract_user_query_tag():
    """Should extract content from <user_query> tag."""
    content = "OS Version: win32\n<user_query>1+1=?</user_query>\n</system-reminder>"
    assert extract_user_query(content) == "1+1=?"


def test_extract_user_query_short():
    """Short content should be returned as-is."""
    assert extract_user_query("hello") == "hello"


def test_build_agent_content_with_tool():
    """Tool result messages should be included."""
    messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "read file"},
        {"role": "tool", "content": "file contents here", "name": "read_file"},
    ]
    content = build_agent_content(messages)
    assert "Tool Result" in content
    assert "file contents" in content
