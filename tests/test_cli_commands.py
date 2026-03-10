"""Tests for the full CLI commands."""

from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from aa.cli import main


def mock_send(response):
    """Return a patcher that mocks send_command to return the given response."""
    return patch("aa.cli.send", return_value=response)


class TestInbox:
    def test_inbox_displays_items(self):
        items = [
            {
                "id": "abc-123",
                "source": "gmail",
                "from_name": "Alice",
                "subject": "Hello",
                "priority": 1,
                "action": "reply",
                "received_at": "2026-03-09T10:00:00",
            },
            {
                "id": "def-456",
                "source": "slack",
                "from_name": "Bob",
                "subject": "Meeting notes",
                "priority": 3,
                "action": "fyi",
                "received_at": "2026-03-09T09:00:00",
            },
        ]
        with mock_send({"ok": True, "items": items}):
            runner = CliRunner()
            result = runner.invoke(main, ["inbox"])
            assert result.exit_code == 0
            assert "Alice" in result.output
            assert "Hello" in result.output
            assert "Bob" in result.output
            assert "Meeting notes" in result.output

    def test_inbox_with_source_filter(self):
        with mock_send({"ok": True, "items": []}) as m:
            runner = CliRunner()
            result = runner.invoke(main, ["inbox", "--source", "slack"])
            assert result.exit_code == 0
            m.assert_called_once()
            call_args = m.call_args[0][0]
            assert call_args["args"]["source"] == "slack"

    def test_inbox_error(self):
        with mock_send({"error": "Daemon is not running. Start it with: aa start"}):
            runner = CliRunner()
            result = runner.invoke(main, ["inbox"])
            assert "Daemon is not running" in result.output


class TestTodo:
    def test_todo_lists_todos(self):
        todos = [
            {
                "id": "todo-1",
                "title": "Buy milk",
                "priority": 2,
                "status": "pending",
                "category": "personal",
                "project": None,
                "due_date": "2026-03-10",
            },
            {
                "id": "todo-2",
                "title": "Write report",
                "priority": 1,
                "status": "pending",
                "category": "work",
                "project": "alpha",
                "due_date": None,
            },
        ]
        with mock_send({"ok": True, "todos": todos}):
            runner = CliRunner()
            result = runner.invoke(main, ["todo"])
            assert result.exit_code == 0
            assert "Buy milk" in result.output
            assert "Write report" in result.output

    def test_todo_list_subcommand(self):
        with mock_send({"ok": True, "todos": []}) as m:
            runner = CliRunner()
            result = runner.invoke(main, ["todo", "list"])
            assert result.exit_code == 0
            m.assert_called_once()

    def test_todo_list_with_filters(self):
        with mock_send({"ok": True, "todos": []}) as m:
            runner = CliRunner()
            result = runner.invoke(
                main, ["todo", "list", "--category", "work", "--project", "alpha"]
            )
            assert result.exit_code == 0
            call_args = m.call_args[0][0]
            assert call_args["args"]["category"] == "work"
            assert call_args["args"]["project"] == "alpha"

    def test_todo_add_creates_todo(self):
        with mock_send({"ok": True, "id": "new-todo-id"}) as m:
            runner = CliRunner()
            result = runner.invoke(
                main,
                ["todo", "add", "Buy groceries", "--priority", "2", "--category", "personal"],
            )
            assert result.exit_code == 0
            call_args = m.call_args[0][0]
            assert call_args["command"] == "todo_add"
            assert call_args["args"]["title"] == "Buy groceries"
            assert call_args["args"]["priority"] == 2
            assert call_args["args"]["category"] == "personal"
            assert "new-todo-id" in result.output

    def test_todo_done(self):
        with mock_send({"ok": True}) as m:
            runner = CliRunner()
            result = runner.invoke(main, ["todo", "done", "todo-1"])
            assert result.exit_code == 0
            call_args = m.call_args[0][0]
            assert call_args["command"] == "todo_done"
            assert call_args["args"]["id"] == "todo-1"

    def test_todo_rm(self):
        with mock_send({"ok": True}) as m:
            runner = CliRunner()
            result = runner.invoke(main, ["todo", "rm", "todo-1"])
            assert result.exit_code == 0
            call_args = m.call_args[0][0]
            assert call_args["command"] == "todo_rm"
            assert call_args["args"]["id"] == "todo-1"


class TestRules:
    def test_rule_add_creates_rule(self):
        with mock_send({"ok": True, "id": "rule-42"}) as m:
            runner = CliRunner()
            result = runner.invoke(main, ["rule", "add", "Emails from boss are P1"])
            assert result.exit_code == 0
            call_args = m.call_args[0][0]
            assert call_args["command"] == "rule_add"
            assert call_args["args"]["rule"] == "Emails from boss are P1"
            assert "rule-42" in result.output

    def test_rule_list(self):
        rules = [
            {"id": "r1", "rule": "Emails from boss are P1"},
            {"id": "r2", "rule": "Slack DMs are P2"},
        ]
        with mock_send({"ok": True, "rules": rules}):
            runner = CliRunner()
            result = runner.invoke(main, ["rule", "list"])
            assert result.exit_code == 0
            assert "Emails from boss are P1" in result.output
            assert "Slack DMs are P2" in result.output

    def test_rule_rm(self):
        with mock_send({"ok": True}) as m:
            runner = CliRunner()
            result = runner.invoke(main, ["rule", "rm", "r1"])
            assert result.exit_code == 0
            call_args = m.call_args[0][0]
            assert call_args["command"] == "rule_rm"
            assert call_args["args"]["id"] == "r1"


class TestStatus:
    def test_status_shows_source_health(self):
        response = {
            "ok": True,
            "status": "running",
            "sources": {
                "gmail": {"status": "ok", "last_sync": "2026-03-09T10:00:00"},
                "slack": {"status": "error", "last_sync": "2026-03-09T09:30:00"},
            },
        }
        with mock_send(response):
            runner = CliRunner()
            result = runner.invoke(main, ["status"])
            assert result.exit_code == 0
            assert "running" in result.output.lower()
            assert "gmail" in result.output
            assert "slack" in result.output


class TestShow:
    def test_show_item(self):
        item = {
            "id": "abc-123",
            "source": "gmail",
            "from_name": "Alice",
            "subject": "Hello",
            "body": "Hi there, how are you?",
            "priority": 1,
            "action": "reply",
            "received_at": "2026-03-09T10:00:00",
        }
        with mock_send({"ok": True, "item": item}):
            runner = CliRunner()
            result = runner.invoke(main, ["show", "abc-123"])
            assert result.exit_code == 0
            assert "Alice" in result.output
            assert "Hello" in result.output
            assert "Hi there" in result.output


class TestCalendar:
    def test_calendar(self):
        events = [
            {
                "id": "ev-1",
                "subject": "Team standup",
                "from_name": "Calendar",
                "received_at": "2026-03-09T09:00:00",
                "source": "calendar",
                "priority": 3,
            },
        ]
        with mock_send({"ok": True, "events": events}):
            runner = CliRunner()
            result = runner.invoke(main, ["calendar"])
            assert result.exit_code == 0
            assert "Team standup" in result.output


class TestAsk:
    def test_ask(self):
        with mock_send({"ok": True, "answer": "42"}) as m:
            runner = CliRunner()
            result = runner.invoke(main, ["ask", "What is the meaning of life?"])
            assert result.exit_code == 0
            call_args = m.call_args[0][0]
            assert call_args["command"] == "ask"
            assert "meaning of life" in call_args["args"]["question"]
