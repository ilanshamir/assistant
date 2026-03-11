"""Interactive shell for the aa personal assistant."""

from __future__ import annotations

import cmd
import shlex
from typing import Any

from aa.cli import send, priority_label, truncate, status_indicator, PRIORITY_COLORS


class AAShell(cmd.Cmd):
    """Interactive shell with tab completion for the aa assistant."""

    prompt = "aa> "

    # Subcommand lists for tab completion
    _todo_subcmds = ["list", "add", "done", "edit", "rm", "link"]
    _rule_subcmds = ["list", "add", "rm"]
    _source_subcmds = ["list", "add", "rm"]

    def __init__(self, send_fn=None):
        super().__init__()
        self.send = send_fn or send
        # Build welcome banner
        try:
            resp = self.send({"command": "status", "args": {}})
            daemon_status = resp.get("status", "unknown")
            inbox_resp = self.send({"command": "inbox", "args": {}})
            inbox_count = len(inbox_resp.get("items", []))
            todo_resp = self.send({"command": "todo", "args": {}})
            todo_count = len(todo_resp.get("todos", []))
            self.intro = (
                f"AA Assistant | daemon: {daemon_status} | "
                f"{inbox_count} unread | {todo_count} todos"
            )
        except Exception:
            self.intro = "AA Assistant | daemon: offline"

    def _print(self, text: str) -> None:
        """Print to stdout (redirectable for testing)."""
        self.stdout.write(text + "\n")

    # ------------------------------------------------------------------
    # Helper: parse flags from args list
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_flags(tokens: list[str], flag_map: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
        """Parse flags from token list. Returns (flags_dict, remaining_args)."""
        flags: dict[str, Any] = {}
        remaining: list[str] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in flag_map:
                key = flag_map[tok]
                if key.startswith("!"):
                    # Boolean flag
                    flags[key[1:]] = True
                else:
                    i += 1
                    if i < len(tokens):
                        flags[key] = tokens[i]
                i += 1
            else:
                remaining.append(tok)
                i += 1
        return flags, remaining

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def do_inbox(self, arg: str) -> None:
        """List inbox items. Usage: inbox [--source SOURCE]"""
        try:
            tokens = shlex.split(arg)
        except ValueError:
            tokens = arg.split()

        args: dict[str, Any] = {}
        flags, _ = self._parse_flags(tokens, {
            "--source": "source", "-s": "source",
        })
        args.update(flags)

        resp = self.send({"command": "inbox", "args": args})
        if "error" in resp and not resp.get("ok"):
            self._print(f"Error: {resp.get('error', 'Unknown error')}")
            return

        items = resp.get("items", [])
        if not items:
            self._print("Inbox is empty.")
            return

        for item in items:
            p = priority_label(item.get("priority"))
            src = truncate(item.get("source", ""), 15)
            frm = truncate(item.get("from_name", ""), 20)
            subj = item.get("subject", "(no subject)")
            iid = item.get("id", "")[:8]
            self._print(f"  {p}  {src:15s}  {frm:20s}  {subj}  [{iid}]")

    def do_show(self, arg: str) -> None:
        """Show item detail. Usage: show ITEM_ID"""
        item_id = arg.strip()
        if not item_id:
            self._print("Usage: show ITEM_ID")
            return
        resp = self.send({"command": "show", "args": {"id": item_id}})
        if "error" in resp and not resp.get("ok"):
            self._print(f"Error: {resp.get('error', 'Unknown error')}")
            return
        item = resp.get("item", {})
        self._print(f"ID:       {item.get('id', '')}")
        self._print(f"Source:   {item.get('source', '')}")
        self._print(f"From:     {item.get('from_name', '')}")
        self._print(f"Subject:  {item.get('subject', '')}")
        self._print(f"Priority: {priority_label(item.get('priority'))}")
        self._print(f"Action:   {item.get('action', '')}")
        self._print(f"Received: {item.get('received_at', '')}")
        self._print(f"\n{item.get('body', '')}")

    def do_reply(self, arg: str) -> None:
        """Request a draft response. Usage: reply ITEM_ID"""
        item_id = arg.strip()
        if not item_id:
            self._print("Usage: reply ITEM_ID")
            return
        resp = self.send({"command": "reply", "args": {"id": item_id}})
        if "error" in resp and not resp.get("ok"):
            self._print(f"Error: {resp.get('error', 'Unknown error')}")
            return
        self._print(resp.get("draft", ""))

    def do_reprioritize(self, arg: str) -> None:
        """Change priority. Usage: reprioritize ITEM_ID PRIORITY"""
        try:
            tokens = shlex.split(arg)
        except ValueError:
            tokens = arg.split()
        if len(tokens) < 2:
            self._print("Usage: reprioritize ITEM_ID PRIORITY")
            return
        item_id, priority = tokens[0], tokens[1]
        try:
            priority_int = int(priority)
        except ValueError:
            self._print("Priority must be an integer.")
            return
        resp = self.send({"command": "reprioritize", "args": {"id": item_id, "priority": priority_int}})
        if "error" in resp and not resp.get("ok"):
            self._print(f"Error: {resp.get('error', 'Unknown error')}")
            return
        self._print("Priority updated.")

    def do_dismiss(self, arg: str) -> None:
        """Dismiss an item. Usage: dismiss ITEM_ID"""
        item_id = arg.strip()
        if not item_id:
            self._print("Usage: dismiss ITEM_ID")
            return
        resp = self.send({"command": "dismiss", "args": {"id": item_id}})
        if "error" in resp and not resp.get("ok"):
            self._print(f"Error: {resp.get('error', 'Unknown error')}")
            return
        self._print("Item dismissed.")

    def do_todo(self, arg: str) -> None:
        """Manage todos. Usage: todo [list|add|done|edit|rm|link] [args]"""
        try:
            tokens = shlex.split(arg)
        except ValueError:
            tokens = arg.split()

        subcmds = {"list", "add", "done", "edit", "rm", "link"}
        if not tokens or tokens[0] == "list" or (tokens[0] not in subcmds):
            # List todos — treat unknown first token (e.g. --all) as implicit "list"
            rest = tokens[1:] if tokens and tokens[0] in subcmds else tokens
            flags, _ = self._parse_flags(rest, {
                "--all": "!all",
                "--category": "category", "-c": "category",
                "--project": "project", "-j": "project",
                "--priority": "priority", "-p": "priority",
                "--urgent": "!urgent", "-u": "!urgent",
                "--keyword": "keyword", "-k": "keyword",
                "--due": "due", "-d": "due",
            })
            args: dict[str, Any] = {}
            if flags.get("all"):
                args["all"] = True
            if flags.get("category"):
                args["category"] = flags["category"]
            if flags.get("project"):
                args["project"] = flags["project"]
            if flags.get("priority"):
                args["priority"] = int(flags["priority"])
            if flags.get("urgent"):
                args["max_priority"] = 2
            if flags.get("keyword"):
                args["keyword"] = flags["keyword"]
            if flags.get("due"):
                from datetime import date, timedelta
                today = date.today()
                val = flags["due"]
                if val == "overdue":
                    args["due_before"] = (today - timedelta(days=1)).isoformat()
                elif val == "today":
                    args["due_before"] = today.isoformat()
                elif val == "week":
                    args["due_before"] = (today + timedelta(days=7)).isoformat()
                else:
                    args["due_before"] = val

            resp = self.send({"command": "todo", "args": args})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            todos = resp.get("todos", [])
            if not todos:
                self._print("No todos.")
                return
            for t in todos:
                ind = status_indicator(t.get("status"))
                p = priority_label(t.get("priority"))
                title = t.get("title", "")
                tid = t.get("id", "")[:8]
                due = t.get("due_date") or ""
                cat = t.get("category") or ""
                parts = [f"  {ind} {p}  {title}  [{tid}]"]
                if due:
                    parts.append(f"due:{due}")
                if cat:
                    parts.append(f"@{cat}")
                self._print("  ".join(parts))

        elif tokens[0] == "add":
            rest = tokens[1:]
            flags, positional = self._parse_flags(rest, {
                "--priority": "priority", "-p": "priority",
                "--due": "due", "-d": "due",
                "--note": "note", "-n": "note",
                "--category": "category", "-c": "category",
                "--project": "project", "-j": "project",
            })
            if not positional:
                self._print("Usage: todo add TITLE [--priority N] [--due DATE]")
                return
            title = " ".join(positional)
            args = {"title": title, "priority": int(flags.get("priority", 3))}
            if flags.get("due"):
                args["due_date"] = flags["due"]
            if flags.get("note"):
                args["note"] = flags["note"]
            if flags.get("category"):
                args["category"] = flags["category"]
            if flags.get("project"):
                args["project"] = flags["project"]
            resp = self.send({"command": "todo_add", "args": args})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            self._print(f"Created todo {resp.get('id', '')}")

        elif tokens[0] == "done":
            if len(tokens) < 2:
                self._print("Usage: todo done TODO_ID")
                return
            resp = self.send({"command": "todo_done", "args": {"id": tokens[1]}})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            self._print("Todo marked as done.")

        elif tokens[0] == "edit":
            if len(tokens) < 2:
                self._print("Usage: todo edit TODO_ID [--title T] [--priority N]")
                return
            todo_id = tokens[1]
            rest = tokens[2:]
            flags, _ = self._parse_flags(rest, {
                "--priority": "priority", "-p": "priority",
                "--title": "title", "-t": "title",
                "--note": "note", "-n": "note",
                "--category": "category", "-c": "category",
                "--project": "project", "-j": "project",
                "--due": "due", "-d": "due",
            })
            args = {"id": todo_id}
            if flags.get("priority"):
                args["priority"] = int(flags["priority"])
            if flags.get("title"):
                args["title"] = flags["title"]
            if flags.get("note"):
                args["note"] = flags["note"]
            if flags.get("category"):
                args["category"] = flags["category"]
            if flags.get("project"):
                args["project"] = flags["project"]
            if flags.get("due"):
                args["due_date"] = flags["due"]
            resp = self.send({"command": "todo_edit", "args": args})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            self._print("Todo updated.")

        elif tokens[0] == "rm":
            if len(tokens) < 2:
                self._print("Usage: todo rm TODO_ID")
                return
            resp = self.send({"command": "todo_rm", "args": {"id": tokens[1]}})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            self._print("Todo removed.")

        elif tokens[0] == "link":
            if len(tokens) < 3:
                self._print("Usage: todo link TODO_ID ITEM_ID")
                return
            resp = self.send({"command": "todo_link", "args": {"todo_id": tokens[1], "item_id": tokens[2]}})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            self._print("Linked.")

        else:
            self._print(f"Unknown todo subcommand: {tokens[0]}")

    def do_calendar(self, arg: str) -> None:
        """Show calendar events. Usage: calendar [when]"""
        when = arg.strip() or "today"
        resp = self.send({"command": "calendar", "args": {"when": when}})
        if "error" in resp and not resp.get("ok"):
            self._print(f"Error: {resp.get('error', 'Unknown error')}")
            return
        events = resp.get("events", [])
        if not events:
            self._print("No events.")
            return
        for ev in events:
            subj = ev.get("subject", "(no subject)")
            time = ev.get("received_at", "")
            self._print(f"  {time}  {subj}")

    def do_ask(self, arg: str) -> None:
        """Ask the AI assistant a question. Usage: ask QUESTION"""
        question = arg.strip()
        if not question:
            self._print("Usage: ask QUESTION")
            return
        resp = self.send({"command": "ask", "args": {"question": question}})
        if "error" in resp and not resp.get("ok"):
            self._print(f"Error: {resp.get('error', 'Unknown error')}")
            return
        self._print(resp.get("answer", ""))

    def do_rule(self, arg: str) -> None:
        """Manage triage rules. Usage: rule [list|add|rm] [args]"""
        try:
            tokens = shlex.split(arg)
        except ValueError:
            tokens = arg.split()

        if not tokens or tokens[0] == "list":
            resp = self.send({"command": "rule_list", "args": {}})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            rules = resp.get("rules", [])
            if not rules:
                self._print("No rules.")
                return
            for r in rules:
                rid = r.get("id", "")
                text = r.get("rule", "")
                self._print(f"  [{rid}]  {text}")

        elif tokens[0] == "add":
            if len(tokens) < 2:
                self._print("Usage: rule add DESCRIPTION")
                return
            description = " ".join(tokens[1:])
            resp = self.send({"command": "rule_add", "args": {"rule": description}})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            self._print(f"Rule added: {resp.get('id', '')}")

        elif tokens[0] == "rm":
            if len(tokens) < 2:
                self._print("Usage: rule rm RULE_ID")
                return
            resp = self.send({"command": "rule_rm", "args": {"id": tokens[1]}})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            self._print("Rule removed.")

        else:
            self._print(f"Unknown rule subcommand: {tokens[0]}")

    def do_source(self, arg: str) -> None:
        """Manage sources. Usage: source [list|add|rm]"""
        self._print("Use the CLI for source management: aa source [list|add|rm]")

    def do_status(self, arg: str) -> None:
        """Show daemon health."""
        resp = self.send({"command": "status", "args": {}})
        if "error" in resp and not resp.get("ok"):
            self._print(f"Error: {resp.get('error', 'Unknown error')}")
            return
        daemon_status = resp.get("status", "unknown")
        self._print(f"Daemon: {daemon_status}")
        sources = resp.get("sources", {})
        if not sources:
            self._print("  No sources configured.")
            return
        for name, state in sources.items():
            src_status = state.get("status", "unknown")
            last = state.get("last_sync", "never")
            self._print(f"  {truncate(name, 15):15s}  {src_status:10s}  last: {last}")

    def do_start(self, arg: str) -> None:
        """Start the daemon."""
        self._print("Use the CLI to start the daemon: aa start")

    def do_stop(self, arg: str) -> None:
        """Stop the daemon."""
        self._print("Use the CLI to stop the daemon: aa stop")

    def do_quit(self, arg: str) -> bool:
        """Exit the shell."""
        return True

    def do_exit(self, arg: str) -> bool:
        """Exit the shell."""
        return True

    def do_EOF(self, arg: str) -> bool:
        """Exit the shell (Ctrl-D)."""
        self._print("")
        return True

    def do_help(self, arg: str) -> None:
        """Show available commands."""
        commands = [
            ("inbox [--source S]", "List inbox items"),
            ("show ITEM_ID", "Show item detail"),
            ("reply ITEM_ID", "Request draft response"),
            ("reprioritize ITEM_ID PRI", "Change priority"),
            ("dismiss ITEM_ID", "Dismiss item"),
            ("todo [list|add|done|edit|rm|link]", "Manage todos"),
            ("calendar [when]", "Show calendar events"),
            ("ask QUESTION", "Ask the AI assistant"),
            ("rule [list|add|rm]", "Manage triage rules"),
            ("source [list|add|rm]", "Manage sources (via CLI)"),
            ("status", "Show daemon health"),
            ("start", "Start daemon (via CLI)"),
            ("stop", "Stop daemon (via CLI)"),
            ("quit / exit", "Exit shell"),
        ]
        self._print("Available commands:")
        for name, desc in commands:
            self._print(f"  {name:35s}  {desc}")

    # ------------------------------------------------------------------
    # Tab completion
    # ------------------------------------------------------------------

    def complete_todo(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        return [s for s in self._todo_subcmds if s.startswith(text)]

    def complete_rule(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        return [s for s in self._rule_subcmds if s.startswith(text)]

    def complete_source(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        return [s for s in self._source_subcmds if s.startswith(text)]
