#!/usr/bin/env python3
"""Fake ACP agent for tests (stdlib only). JSON-RPC 2.0 over stdio, one message per line.

Usage: fake_acp_agent.py --scenario NAME [--record FILE] [--system-prompt]

Scenarios (PLAN "Commands"):
  echo         "Echo: <prompt>" in 3 agent_message_chunk fragments; a prompt starting with
               "md:" gets markdown with a table and a code block instead
  thinking     two agent_thought_chunk fragments, then the echo reply
  tool         a thought fragment, tool_call (pending), tool_call_update in_progress and
               completed (with content), then a text reply
  permission   tool_call, session/request_permission (allow_once / reject_once); allowed →
               tool completed + "Zezwolono", rejected → tool failed + "Odmowa", cancelled →
               stopReason "cancelled"
  slow         one fragment every 200 ms for 10 s; session/cancel → stopReason "cancelled"
  crash        after session/prompt writes "boom" to stderr and exits with code 3
  crash-once   like crash for the first prompt only (marker file in the session cwd)
  bad-version  initialize answers protocolVersion 99
  auth         initialize lists authMethods; session/new fails with -32000 auth_required
  noise        non-JSON lines on stdout at start and around every message; otherwise echo
  models       configOptions with category "model"; session/set_config_option changes it;
               replies are prefixed with "[<model>] "
  load         agentCapabilities.loadSession = true; session/load replays a short history
  usage        echo, then a usage_update notification
  image        promptCapabilities.image = true; describes every received image
  env          replies with the value of the environment variable named in the prompt

--record FILE appends {"method", "params"} of every initialize, session/new, session/load and
session/prompt as one JSON line.

--system-prompt advertises agentCapabilities.sessionCapabilities.systemPrompt = {} (clients
may then send systemPrompt in session/new).
"""

import argparse
import asyncio
import base64
import binascii
import json
import os
import sys
import threading
from pathlib import Path

SCENARIOS = (
    "echo",
    "thinking",
    "tool",
    "permission",
    "slow",
    "crash",
    "crash-once",
    "bad-version",
    "auth",
    "noise",
    "models",
    "load",
    "usage",
    "image",
    "env",
)
RECORDED_METHODS = ("initialize", "session/new", "session/load", "session/prompt")
CRASH_MARKER = ".fake-acp-crash-once"
AUTH_METHODS = [
    {
        "id": "fake-login",
        "name": "Fake login",
        "description": "Run `fake-agent login` in a terminal",
    }
]
MODELS = [
    {"value": "fake-small", "name": "Fake Small"},
    {"value": "fake-large", "name": "Fake Large"},
]
MARKDOWN_REPLY = [
    "## Wynik\n\n| Kolumna | Wartość |\n|---|---|\n",
    "| a | 1 |\n| b | 2 |\n\n",
    "```python\nprint('Echo')\n```\n",
]
SLOW_INTERVAL_S = 0.2
SLOW_DURATION_S = 10.0
EOF_GRACE_S = 2.0


class Agent:
    def __init__(self, scenario: str, record: str | None, system_prompt: bool = False) -> None:
        self.scenario = scenario
        self.system_prompt = system_prompt
        self.record = Path(record) if record else None
        self.loop = asyncio.get_running_loop()
        self.next_session = 1
        self.next_request = 1000
        self.sessions: dict[str, dict] = {}
        self.pending: dict[int, asyncio.Future] = {}
        self.cancelled: set[str] = set()
        self.tasks: set[asyncio.Task] = set()

    # -- output --------------------------------------------------------------------------

    def write(self, message: dict) -> None:
        if self.scenario == "noise":
            sys.stdout.buffer.write(b"[fake-agent] noise before message\n")
        sys.stdout.buffer.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
        if self.scenario == "noise":
            sys.stdout.buffer.write(b"not json {\n")
        sys.stdout.buffer.flush()

    def respond(self, request_id, result) -> None:
        self.write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def respond_error(self, request_id, code: int, message: str, data=None) -> None:
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        self.write({"jsonrpc": "2.0", "id": request_id, "error": error})

    def update(self, session_id: str, update: dict) -> None:
        self.write(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": session_id, "update": update},
            }
        )

    def chunk(self, session_id: str, text: str, kind: str = "agent_message_chunk") -> None:
        self.update(session_id, {"sessionUpdate": kind, "content": {"type": "text", "text": text}})

    async def request(self, method: str, params: dict):
        request_id = self.next_request
        self.next_request += 1
        future = self.loop.create_future()
        self.pending[request_id] = future
        self.write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            return await future
        finally:
            self.pending.pop(request_id, None)

    def save(self, method: str, params) -> None:
        if self.record is None or method not in RECORDED_METHODS:
            return
        with self.record.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"method": method, "params": params}, ensure_ascii=False) + "\n")

    # -- dispatch ------------------------------------------------------------------------

    def handle(self, message: dict) -> None:
        method = message.get("method")
        if method is None:
            future = self.pending.get(message.get("id"))
            if future is not None and not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError(json.dumps(message["error"])))
                else:
                    future.set_result(message.get("result"))
            return
        params = message.get("params") or {}
        self.save(method, params)
        if "id" not in message:
            if method == "session/cancel":
                self.cancelled.add(params.get("sessionId"))
            return
        request_id = message["id"]
        if method == "session/prompt":
            # Reset the cancel flag here, in message order: a session/cancel read right after
            # this prompt (before its task runs) must still cancel it.
            self.cancelled.discard(params.get("sessionId"))
            task = self.loop.create_task(self.prompt(request_id, params))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            return
        handler = {
            "initialize": self.initialize,
            "session/new": self.new_session,
            "session/load": self.load_session,
            "session/set_config_option": self.set_config_option,
        }.get(method)
        if handler is None:
            self.respond_error(request_id, -32601, f"Method not found: {method}")
            return
        handler(request_id, params)

    def initialize(self, request_id, params) -> None:
        version = 99 if self.scenario == "bad-version" else 1
        capabilities: dict = {
            "loadSession": self.scenario == "load",
            "promptCapabilities": {
                "image": self.scenario == "image",
                "audio": False,
                "embeddedContext": False,
            },
        }
        if self.system_prompt:
            capabilities["sessionCapabilities"] = {"systemPrompt": {}}
        self.respond(
            request_id,
            {
                "protocolVersion": version,
                "agentCapabilities": capabilities,
                "agentInfo": {
                    "name": "fake-acp-agent",
                    "title": "Fake ACP Agent",
                    "version": "1.0.0",
                },
                "authMethods": AUTH_METHODS if self.scenario == "auth" else [],
            },
        )

    def new_session(self, request_id, params) -> None:
        if self.scenario == "auth":
            self.respond_error(
                request_id, -32000, "Authentication required", {"reason": "auth_required"}
            )
            return
        session_id = f"sess_{self.next_session}"
        self.next_session += 1
        self.sessions[session_id] = {"cwd": params.get("cwd") or os.getcwd(), "model": "fake-small"}
        result: dict = {"sessionId": session_id}
        if self.scenario == "models":
            result["configOptions"] = self.config_options(session_id)
        self.respond(request_id, result)

    def load_session(self, request_id, params) -> None:
        if self.scenario != "load":
            self.respond_error(request_id, -32601, "Method not found: session/load")
            return
        session_id = params.get("sessionId", "")
        self.sessions[session_id] = {"cwd": params.get("cwd") or os.getcwd(), "model": "fake-small"}
        self.chunk(session_id, "Poprzednie pytanie", "user_message_chunk")
        self.chunk(session_id, "Poprzednia odpowiedź")
        self.respond(request_id, {})

    def config_options(self, session_id: str) -> list:
        return [
            {
                "id": "model",
                "name": "Model",
                "category": "model",
                "type": "select",
                "currentValue": self.sessions[session_id]["model"],
                "options": MODELS,
            }
        ]

    def set_config_option(self, request_id, params) -> None:
        session_id = params.get("sessionId")
        values = [m["value"] for m in MODELS]
        if self.scenario != "models" or session_id not in self.sessions:
            self.respond_error(request_id, -32602, "Invalid params")
            return
        if params.get("configId") != "model" or params.get("value") not in values:
            self.respond_error(request_id, -32602, "Invalid params")
            return
        self.sessions[session_id]["model"] = params["value"]
        self.respond(request_id, {"configOptions": self.config_options(session_id)})

    # -- prompt turns --------------------------------------------------------------------

    async def prompt(self, request_id, params) -> None:
        session_id = params.get("sessionId")
        if session_id not in self.sessions:
            self.respond_error(request_id, -32602, f"Unknown session: {session_id}")
            return
        blocks = params.get("prompt") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        stop_reason = await self.turn(session_id, text, blocks)
        self.respond(request_id, {"stopReason": stop_reason})

    def echo(self, session_id: str, text: str, prefix: str = "") -> None:
        if text.startswith("md:"):
            for part in MARKDOWN_REPLY:
                self.chunk(session_id, part)
            return
        half = len(text) // 2
        for part in (f"{prefix}Echo: ", text[:half], text[half:]):
            self.chunk(session_id, part)

    async def turn(self, session_id: str, text: str, blocks: list) -> str:
        scenario = self.scenario
        if scenario == "crash" or scenario == "crash-once" and self.first_crash(session_id):
            sys.stderr.write("boom\n")
            sys.stderr.flush()
            os._exit(3)
        if scenario == "thinking":
            self.chunk(session_id, "Zastanawiam się ", "agent_thought_chunk")
            self.chunk(session_id, "nad odpowiedzią.", "agent_thought_chunk")
        elif scenario == "tool":
            await self.tool(session_id)
            return "end_turn"
        elif scenario == "permission":
            return await self.permission(session_id)
        elif scenario == "slow":
            return await self.slow(session_id)
        elif scenario == "env":
            name = text.strip()
            self.chunk(session_id, os.environ.get(name, f"<brak {name}>"))
            return "end_turn"
        elif scenario == "image":
            for block in blocks:
                if block.get("type") == "image":
                    self.chunk(session_id, describe_image(block) + "\n")
        prefix = f"[{self.sessions[session_id]['model']}] " if scenario == "models" else ""
        self.echo(session_id, text, prefix)
        if scenario == "usage":
            self.update(
                session_id,
                {
                    "sessionUpdate": "usage_update",
                    "used": 1234,
                    "size": 200000,
                    "cost": {"amount": 0.0123, "currency": "USD"},
                },
            )
        return "end_turn"

    def first_crash(self, session_id: str) -> bool:
        marker = Path(self.sessions[session_id]["cwd"]) / CRASH_MARKER
        if marker.exists():
            return False
        marker.write_text("crashed once\n", encoding="utf-8")
        return True

    async def tool(self, session_id: str) -> None:
        self.chunk(session_id, "Sprawdzę plik.", "agent_thought_chunk")
        self.update(
            session_id,
            {
                "sessionUpdate": "tool_call",
                "toolCallId": "call_1",
                "title": "Odczyt pliku notes.txt",
                "kind": "read",
                "status": "pending",
                "rawInput": {"path": "notes.txt"},
            },
        )
        await asyncio.sleep(0.01)
        self.update(
            session_id,
            {"sessionUpdate": "tool_call_update", "toolCallId": "call_1", "status": "in_progress"},
        )
        await asyncio.sleep(0.01)
        self.update(
            session_id,
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call_1",
                "status": "completed",
                "content": [{"type": "content", "content": {"type": "text", "text": "zawartość"}}],
            },
        )
        self.chunk(session_id, "Plik zawiera: zawartość.")

    async def permission(self, session_id: str) -> str:
        tool_call = {
            "toolCallId": "call_perm",
            "title": "Zapis pliku out.txt",
            "kind": "edit",
            "status": "pending",
            "rawInput": {"path": "out.txt", "content": "x"},
        }
        self.update(session_id, {"sessionUpdate": "tool_call", **tool_call})
        result = await self.request(
            "session/request_permission",
            {
                "sessionId": session_id,
                "toolCall": tool_call,
                "options": [
                    {"optionId": "allow", "name": "Zezwól", "kind": "allow_once"},
                    {"optionId": "reject", "name": "Odrzuć", "kind": "reject_once"},
                ],
            },
        )
        outcome = (result or {}).get("outcome") or {}
        if outcome.get("outcome") == "cancelled" or session_id in self.cancelled:
            self.update(
                session_id,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": "call_perm",
                    "status": "failed",
                },
            )
            return "cancelled"
        allowed = outcome.get("outcome") == "selected" and outcome.get("optionId") == "allow"
        self.update(
            session_id,
            {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call_perm",
                "status": "completed" if allowed else "failed",
            },
        )
        self.chunk(session_id, "Zezwolono" if allowed else "Odmowa")
        return "end_turn"

    async def slow(self, session_id: str) -> str:
        steps = int(SLOW_DURATION_S / SLOW_INTERVAL_S)
        for i in range(steps):
            if session_id in self.cancelled:
                return "cancelled"
            self.chunk(session_id, f"fragment {i + 1} ")
            await asyncio.sleep(SLOW_INTERVAL_S)
        return "cancelled" if session_id in self.cancelled else "end_turn"


def describe_image(block: dict) -> str:
    try:
        size = len(base64.b64decode(block.get("data", ""), validate=True))
    except (binascii.Error, ValueError):
        size = -1
    return f"Obraz: {block.get('mimeType', '?')}, {size} bajtów"


def start_stdin_reader(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    def run() -> None:
        for line in sys.stdin.buffer:
            loop.call_soon_threadsafe(queue.put_nowait, line)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=run, daemon=True).start()


async def main_async(args: argparse.Namespace) -> int:
    agent = Agent(args.scenario, args.record, args.system_prompt)
    if args.scenario == "noise":
        sys.stdout.buffer.write(b"Fake agent starting...\n\n")
        sys.stdout.buffer.flush()
    queue: asyncio.Queue = asyncio.Queue()
    start_stdin_reader(asyncio.get_running_loop(), queue)
    while (line := await queue.get()) is not None:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict):
            agent.handle(message)
    # End of input: let short turns finish (e.g. `printf … | fake_acp_agent.py`), then stop.
    if agent.tasks:
        _, still_running = await asyncio.wait(list(agent.tasks), timeout=EOF_GRACE_S)
        for task in still_running:
            task.cancel()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fake ACP agent for tests")
    parser.add_argument("--scenario", choices=SCENARIOS, default="echo")
    parser.add_argument("--record", metavar="FILE")
    parser.add_argument("--system-prompt", action="store_true")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
