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
    _todo_subcmds = ["list", "show", "add", "done", "edit", "rm", "link", "export"]
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
        """List inbox items. Usage: inbox [--source/-s SOURCE]"""
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
        linked_todos = resp.get("linked_todos", [])
        if linked_todos:
            self._print(f"\nLinked todos:")
            for t in linked_todos:
                p = priority_label(t.get("priority"))
                tid = t.get("id", "")[:8]
                self._print(f"  {p}  {t.get('title', '')}  [{tid}]")
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
        """Manage todos. Usage: todo [list|show|add|done|edit|rm|link] [args]
        list: [--all] [--details] [--category/-c CAT] [--project/-j PROJ] [--priority/-p N] [--urgent/-u] [--keyword/-k TEXT] [--due/-d DATE]
        show: TODO_ID
        add:  TITLE [--priority/-p N] [--due/-d DATE] [--note/-n TEXT] [--details TEXT] [--category/-c CAT] [--project/-j PROJ]
        edit: TODO_ID [--title/-t T] [--priority/-p N] [--note/-n TEXT] [--details TEXT] [--category/-c CAT] [--project/-j PROJ] [--due/-d DATE]
        done: TODO_ID | rm: TODO_ID | link: TODO_ID ITEM_ID"""
        try:
            tokens = shlex.split(arg)
        except ValueError:
            tokens = arg.split()

        subcmds = {"list", "show", "add", "done", "edit", "rm", "link", "export"}
        if not tokens or tokens[0] == "list" or (tokens[0] not in subcmds):
            # Parse flags first to decide: list or bulk edit?
            rest = tokens[1:] if tokens and tokens[0] in subcmds else tokens
            edit_flag_map = {
                "--priority": "priority", "-p": "priority",
                "--title": "title", "-t": "title",
                "--note": "note", "-n": "note",
                "--details": "details",
                "--category": "category", "-c": "category",
                "--project": "project", "-j": "project",
                "--due": "due", "-d": "due",
            }
            list_flag_map = {
                "--all": "!all",
                "--details": "!details_flag",
                "--urgent": "!urgent", "-u": "!urgent",
                "--keyword": "keyword", "-k": "keyword",
            }
            # Merge both flag maps for parsing
            combined_flags = {**edit_flag_map, **list_flag_map}
            flags, positional = self._parse_flags(rest, combined_flags)

            # If there are positional args (IDs) and edit-type flags, treat as bulk edit
            edit_keys = {"priority", "title", "note", "details", "category", "due"}
            has_edit_flags = bool(edit_keys & set(flags.keys()))
            if positional and has_edit_flags:
                edit_args: dict[str, Any] = {}
                if flags.get("priority"):
                    edit_args["priority"] = int(flags["priority"])
                if flags.get("title"):
                    edit_args["title"] = flags["title"]
                if flags.get("note"):
                    edit_args["note"] = flags["note"]
                if flags.get("details"):
                    edit_args["details"] = flags["details"]
                if flags.get("category"):
                    edit_args["category"] = flags["category"]
                if flags.get("due"):
                    edit_args["due_date"] = flags["due"]
                for todo_id in positional:
                    resp = self.send({"command": "todo_edit", "args": {"id": todo_id, **edit_args}})
                    if "error" in resp and not resp.get("ok"):
                        self._print(f"Error [{todo_id}]: {resp.get('error', 'Unknown error')}")
                    else:
                        self._print(f"Updated {todo_id}")
                return

            # Otherwise it's a list command
            args: dict[str, Any] = {}
            show_details = flags.get("details_flag", False)
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
                has_details = bool(t.get("details"))
                parts = [f"  {ind} {p}  {title}  [{tid}]"]
                if due:
                    parts.append(f"due:{due}")
                if cat:
                    parts.append(f"@{cat}")
                if has_details:
                    parts.append("[+]")
                self._print("  ".join(parts))
                if show_details and has_details:
                    for line in t["details"].splitlines():
                        self._print(f"       {line}")

        elif tokens[0] == "show":
            if len(tokens) < 2:
                self._print("Usage: todo show TODO_ID")
                return
            resp = self.send({"command": "todo_show", "args": {"id": tokens[1]}})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            t = resp.get("todo", {})
            self._print(f"ID:       {t.get('id', '')}")
            self._print(f"Title:    {t.get('title', '')}")
            self._print(f"Priority: {priority_label(t.get('priority'))}")
            self._print(f"Status:   {t.get('status', '')}")
            cat = t.get("category") or ""
            proj = t.get("project") or ""
            due = t.get("due_date") or ""
            if cat:
                self._print(f"Category: {cat}")
            if proj:
                self._print(f"Project:  {proj}")
            if due:
                self._print(f"Due:      {due}")
            notes = t.get("notes") or ""
            if notes:
                self._print(f"Notes:    {notes}")
            details = t.get("details") or ""
            if details:
                self._print(f"\nDetails:\n{details}")
            linked_items = resp.get("linked_items", [])
            if linked_items:
                self._print(f"\nLinked items:")
                for item in linked_items:
                    src = truncate(item.get("source", ""), 15)
                    subj = item.get("subject", "(no subject)")
                    iid = item.get("id", "")[:8]
                    self._print(f"  {src:15s}  {subj}  [{iid}]")

        elif tokens[0] == "add":
            rest = tokens[1:]
            flags, positional = self._parse_flags(rest, {
                "--priority": "priority", "-p": "priority",
                "--due": "due", "-d": "due",
                "--note": "note", "-n": "note",
                "--details": "details",
                "--category": "category", "-c": "category",
                "--project": "project", "-j": "project",
            })
            if not positional:
                self._print("Usage: todo add TITLE [--priority/-p N] [--due/-d DATE] [--note/-n TEXT] [--details TEXT] [--category/-c CAT] [--project/-j PROJ]")
                return
            title = " ".join(positional)
            args = {"title": title, "priority": int(flags.get("priority", 3))}
            if flags.get("due"):
                args["due_date"] = flags["due"]
            if flags.get("note"):
                args["note"] = flags["note"]
            if flags.get("details"):
                args["details"] = flags["details"]
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
                self._print("Usage: todo done TODO_ID [TODO_ID ...]")
                return
            for todo_id in tokens[1:]:
                resp = self.send({"command": "todo_done", "args": {"id": todo_id}})
                if "error" in resp and not resp.get("ok"):
                    self._print(f"Error [{todo_id}]: {resp.get('error', 'Unknown error')}")
                else:
                    self._print(f"Done: {todo_id}")

        elif tokens[0] == "edit":
            rest = tokens[1:]
            flags, positional = self._parse_flags(rest, {
                "--priority": "priority", "-p": "priority",
                "--title": "title", "-t": "title",
                "--note": "note", "-n": "note",
                "--details": "details",
                "--category": "category", "-c": "category",
                "--project": "project", "-j": "project",
                "--due": "due", "-d": "due",
            })
            if not positional:
                self._print("Usage: todo edit TODO_ID [TODO_ID ...] [--title/-t T] [--priority/-p N] [--note/-n TEXT] [--details TEXT] [--category/-c CAT] [--project/-j PROJ] [--due/-d DATE]")
                return
            edit_args: dict[str, Any] = {}
            if flags.get("priority"):
                edit_args["priority"] = int(flags["priority"])
            if flags.get("title"):
                edit_args["title"] = flags["title"]
            if flags.get("note"):
                edit_args["note"] = flags["note"]
            if flags.get("details"):
                edit_args["details"] = flags["details"]
            if flags.get("category"):
                edit_args["category"] = flags["category"]
            if flags.get("project"):
                edit_args["project"] = flags["project"]
            if flags.get("due"):
                edit_args["due_date"] = flags["due"]
            for todo_id in positional:
                resp = self.send({"command": "todo_edit", "args": {"id": todo_id, **edit_args}})
                if "error" in resp and not resp.get("ok"):
                    self._print(f"Error [{todo_id}]: {resp.get('error', 'Unknown error')}")
                else:
                    self._print(f"Updated {todo_id}")

        elif tokens[0] == "rm":
            if len(tokens) < 2:
                self._print("Usage: todo rm TODO_ID [TODO_ID ...]")
                return
            for todo_id in tokens[1:]:
                resp = self.send({"command": "todo_rm", "args": {"id": todo_id}})
                if "error" in resp and not resp.get("ok"):
                    self._print(f"Error [{todo_id}]: {resp.get('error', 'Unknown error')}")
                else:
                    self._print(f"Removed {todo_id}")

        elif tokens[0] == "link":
            if len(tokens) < 3:
                self._print("Usage: todo link TODO_ID ITEM_ID")
                return
            resp = self.send({"command": "todo_link", "args": {"todo_id": tokens[1], "item_id": tokens[2]}})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            self._print("Linked.")

        elif tokens[0] == "export":
            from aa.cli import export_todos_csv, _default_export_path
            rest = tokens[1:]
            flags, _ = self._parse_flags(rest, {
                "--output": "output", "-o": "output",
            })
            output = flags.get("output") or _default_export_path()
            resp = self.send({"command": "todo_export", "args": {}})
            if "error" in resp and not resp.get("ok"):
                self._print(f"Error: {resp.get('error', 'Unknown error')}")
                return
            todos = resp.get("todos", [])
            if not todos:
                self._print("No todos to export.")
                return
            export_todos_csv(todos, output)
            self._print(f"Exported {len(todos)} todos to {output}")

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
        """Manage sources. Usage: source [list|add|rm] [args]"""
        from aa.cli import list_sources, add_source, remove_source, VALID_SOURCE_TYPES

        try:
            tokens = shlex.split(arg)
        except ValueError:
            tokens = arg.split()

        if not tokens or tokens[0] == "list":
            for line in list_sources():
                self._print(line)

        elif tokens[0] == "add":
            rest = tokens[1:]
            flags, positional = self._parse_flags(rest, {
                "--type": "type", "-t": "type",
                "--credentials-file": "credentials_file",
                "--client-id": "client_id",
                "--tenant-id": "tenant_id",
                "--token": "token",
                "--url": "url",
                "--channels": "channels",
                "--path": "path",
            })
            if not positional or not flags.get("type"):
                self._print(
                    "Usage: source add NAME --type TYPE [options]\n"
                    f"  Types: {', '.join(VALID_SOURCE_TYPES)}"
                )
                return
            try:
                msg = add_source(
                    positional[0], flags["type"],
                    credentials_file=flags.get("credentials_file"),
                    client_id=flags.get("client_id"),
                    tenant_id=flags.get("tenant_id"),
                    token=flags.get("token"),
                    url=flags.get("url"),
                    channels=flags.get("channels"),
                    path=flags.get("path"),
                )
                self._print(msg)
            except ValueError as e:
                self._print(f"Error: {e}")

        elif tokens[0] == "rm":
            if len(tokens) < 2:
                self._print("Usage: source rm NAME")
                return
            try:
                self._print(remove_source(tokens[1]))
            except ValueError as e:
                self._print(f"Error: {e}")

        else:
            self._print(f"Unknown source subcommand: {tokens[0]}")

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
            last = state.get("updated_at") or state.get("last_sync") or "never"
            self._print(f"  {truncate(name, 15):15s}  {src_status:10s}  last: {last}")

    def do_start(self, arg: str) -> None:
        """Start the daemon."""
        from aa.cli import start_daemon
        self._print(start_daemon())

    def do_stop(self, arg: str) -> None:
        """Stop the daemon."""
        from aa.cli import stop_daemon
        self._print(stop_daemon())

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
            ("inbox [--source/-s S]", "List inbox items"),
            ("show ITEM_ID", "Show item detail"),
            ("reply ITEM_ID", "Request draft response"),
            ("reprioritize ITEM_ID PRI", "Change priority"),
            ("dismiss ITEM_ID", "Dismiss item"),
            ("todo list [--all] [--details] ...", "List todos"),
            ("todo show TODO_ID", "Show todo detail"),
            ("todo add TITLE [--priority/-p N] ...", "Add a todo"),
            ("todo done TODO_ID", "Mark todo as done"),
            ("todo edit TODO_ID [--title/-t] ...", "Edit a todo"),
            ("todo rm TODO_ID", "Remove a todo"),
            ("todo link TODO_ID ITEM_ID", "Link todo to item"),
            ("todo export [--output/-o FILE]", "Export all todos to CSV"),
            ("calendar [when]", "Show calendar events"),
            ("ask QUESTION", "Ask the AI assistant"),
            ("rule [list|add|rm]", "Manage triage rules"),
            ("source list", "List sources"),
            ("source add NAME --type/-t TYPE ...", "Add a source"),
            ("source rm NAME", "Remove a source"),
            ("status", "Show daemon health"),
            ("start", "Start daemon"),
            ("stop", "Stop daemon"),
            ("quit / exit", "Exit shell"),
        ]
        self._print("Available commands:")
        for name, desc in commands:
            self._print(f"  {name:40s}  {desc}")

    # ------------------------------------------------------------------
    # Tab completion
    # ------------------------------------------------------------------

    def complete_todo(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        return [s for s in self._todo_subcmds if s.startswith(text)]

    def complete_rule(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        return [s for s in self._rule_subcmds if s.startswith(text)]

    def complete_source(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        return [s for s in self._source_subcmds if s.startswith(text)]
