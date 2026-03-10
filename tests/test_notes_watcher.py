import pytest
from aa.notes_watcher import extract_new_content


def test_new_content_detected_from_diff():
    old = "line one\nline two\n"
    new = "line one\nline two\nline three\nline four\n"
    result = extract_new_content(old, new)
    assert "line three" in result
    assert "line four" in result
    assert "line one" not in result
    assert "line two" not in result


def test_no_change_returns_empty_string():
    text = "line one\nline two\nline three\n"
    result = extract_new_content(text, text)
    assert result == ""


def test_from_empty_to_content():
    old = ""
    new = "hello world\nsecond line\n"
    result = extract_new_content(old, new)
    assert "hello world" in result
    assert "second line" in result
