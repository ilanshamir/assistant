"""Tests for the request handler and socket server."""

from __future__ import annotations

import pytest

from aa.server import RequestHandler


class TestParseRequest:
    """Tests for RequestHandler.parse_request."""

    def test_valid_json(self):
        handler = RequestHandler.__new__(RequestHandler)
        result = handler.parse_request('{"command": "status", "args": {}}')
        assert result == {"command": "status", "args": {}}

    def test_valid_json_complex(self):
        handler = RequestHandler.__new__(RequestHandler)
        data = '{"command": "todo_add", "args": {"title": "Buy milk", "priority": 2}}'
        result = handler.parse_request(data)
        assert result == {"command": "todo_add", "args": {"title": "Buy milk", "priority": 2}}

    def test_invalid_json_returns_none(self):
        handler = RequestHandler.__new__(RequestHandler)
        assert handler.parse_request("not valid json") is None

    def test_empty_string_returns_none(self):
        handler = RequestHandler.__new__(RequestHandler)
        assert handler.parse_request("") is None

    def test_partial_json_returns_none(self):
        handler = RequestHandler.__new__(RequestHandler)
        assert handler.parse_request('{"command":') is None
