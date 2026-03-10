"""Tests for the interactive shell."""

from __future__ import annotations

import io

from aa.shell import AAShell


def make_shell(**send_responses):
    """Create a shell with mocked send function."""
    default_status = {"ok": True, "status": "running", "sources": {}}
    default_inbox = {"ok": True, "items": []}
    default_todos = {"ok": True, "todos": []}
    responses = {
        "status": default_status,
        "inbox": default_inbox,
        "todo": default_todos,
        **send_responses,
    }

    def mock_send(request):
        cmd = request.get("command", "")
        return responses.get(cmd, {"ok": True})

    shell = AAShell.__new__(AAShell)
    shell.send = mock_send
    shell.prompt = "aa> "
    shell.use_rawinput = False
    return shell


def _run(shell, command: str) -> str:
    """Run a command on the shell and capture stdout."""
    out = io.StringIO()
    shell.stdout = out
    method = getattr(shell, f"do_{command.split()[0]}")
    arg = command[len(command.split()[0]):].strip()
    method(arg)
    return out.getvalue()


class TestInbox:
    def test_inbox_displays_items(self):
        shell = make_shell(
            inbox={
                "ok": True,
                "items": [
                    {
                        "id": "abc12345-xxxx",
                        "source": "gmail",
                        "from_name": "Alice",
                        "subject": "Hello",
                        "priority": 2,
                    }
                ],
            }
        )
        output = _run(shell, "inbox")
        assert "Alice" in output


class TestStatus:
    def test_status_shows_running(self):
        shell = make_shell()
        output = _run(shell, "status")
        assert "running" in output


class TestTodo:
    def test_todo_no_args_lists(self):
        shell = make_shell(
            todo={
                "ok": True,
                "todos": [
                    {"id": "t1234567", "title": "Buy milk", "priority": 3, "status": "open"}
                ],
            }
        )
        output = _run(shell, "todo")
        assert "Buy milk" in output

    def test_todo_add_sends_command(self):
        sent = {}

        def mock_send(request):
            sent.update(request)
            return {"ok": True, "id": "new123"}

        shell = AAShell.__new__(AAShell)
        shell.send = mock_send
        shell.prompt = "aa> "
        shell.use_rawinput = False

        out = io.StringIO()
        shell.stdout = out
        shell.do_todo('add "Buy groceries"')
        assert sent.get("command") == "todo_add"
        assert sent["args"]["title"] == "Buy groceries"


class TestQuitExitEOF:
    def test_quit_returns_true(self):
        shell = make_shell()
        result = shell.do_quit("")
        assert result is True

    def test_exit_returns_true(self):
        shell = make_shell()
        result = shell.do_exit("")
        assert result is True

    def test_eof_returns_true(self):
        shell = make_shell()
        shell.stdout = io.StringIO()
        result = shell.do_EOF("")
        assert result is True


class TestHelp:
    def test_help_lists_commands(self):
        shell = make_shell()
        out = io.StringIO()
        shell.stdout = out
        shell.do_help("")
        output = out.getvalue()
        assert "inbox" in output
        assert "todo" in output
        assert "status" in output


class TestCompletion:
    def test_complete_todo_returns_subcommands(self):
        shell = make_shell()
        results = shell.complete_todo("", "todo ", 5, 5)
        assert "list" in results
        assert "add" in results
        assert "done" in results
        assert "edit" in results
        assert "rm" in results
        assert "link" in results

    def test_complete_todo_filters(self):
        shell = make_shell()
        results = shell.complete_todo("a", "todo a", 5, 6)
        assert "add" in results
        assert "list" not in results

    def test_complete_rule_returns_subcommands(self):
        shell = make_shell()
        results = shell.complete_rule("", "rule ", 5, 5)
        assert "list" in results
        assert "add" in results
        assert "rm" in results

    def test_complete_source_returns_subcommands(self):
        shell = make_shell()
        results = shell.complete_source("", "source ", 7, 7)
        assert "list" in results
        assert "add" in results
        assert "rm" in results
