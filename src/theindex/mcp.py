# SPDX-License-Identifier: MIT
"""A minimal MCP server (stdio, newline-delimited JSON-RPC 2.0) over the shared query layer. Standard library only.
Silent on success: stdout carries protocol messages only, stderr only errors."""
import json
import sys

from . import __version__
from .mcp_tools import INSTRUCTIONS, Session, error_result, tools

SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
PARSE, INVALID, NO_METHOD, BAD_PARAMS = -32700, -32600, -32601, -32602


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _initialize(params):
    if not isinstance(params, dict):
        raise RpcError(BAD_PARAMS, "params must be an object")
    wanted = params.get("protocolVersion")
    return {"protocolVersion": wanted if wanted in SUPPORTED else SUPPORTED[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "the-index", "version": __version__}, "instructions": INSTRUCTIONS}


def _call(session, params):
    if not isinstance(params, dict) or not isinstance(params.get("name"), str):
        raise RpcError(BAD_PARAMS, "tools/call needs a string `name`")
    try:
        return session.call(params["name"], params.get("arguments"))
    except Exception as exc:  # noqa: BLE001 - a failing query is a tool error, never a crash
        print(f"the-index mcp: {exc}", file=sys.stderr)
        return error_result(f"query failed: {exc}")


def handle(session, method, params):
    """The result for one request method; raises RpcError."""
    if method == "initialize":
        return _initialize(params)
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tools()}
    if method == "tools/call":
        return _call(session, params)
    raise RpcError(NO_METHOD, f"method not found: {method}")


def _reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    out.update({"error": error} if error else {"result": result})
    return out


def process(session, line):
    """The reply message for one input line, or None (notifications and client responses get no reply)."""
    try:
        msg = json.loads(line)
    except ValueError:
        return _reply(None, error={"code": PARSE, "message": "parse error"})
    if not isinstance(msg, dict) or not isinstance(msg.get("method"), str):
        if isinstance(msg, dict) and "method" not in msg and "id" in msg:
            return None   # a response from the client: nothing to do
        return _reply(None, error={"code": INVALID, "message": "invalid request"})
    if "id" not in msg:
        return None
    try:
        return _reply(msg["id"], handle(session, msg["method"], msg.get("params")))
    except RpcError as exc:
        return _reply(msg["id"], error={"code": exc.code, "message": exc.message})


def serve(cfg, stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    session = Session(cfg)
    for line in stdin:
        if not line.strip():
            continue
        reply = process(session, line)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
