# SPDX-License-Identifier: MIT
"""The MCP stdio server, run as a subprocess against a temp database."""
import json
import os
import subprocess
import sys
from pathlib import Path

from test_query import QueryCase

from theindex import db, query

SRC = str(Path(__file__).resolve().parent.parent / "src")


def rpc(msg_id, method, params=None):
    msg = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


def serve(db_path, lines):
    """Run `the-index mcp` with the lines on stdin; returns (parsed stdout lines, stderr)."""
    env = {**os.environ, "PYTHONPATH": SRC}
    proc = subprocess.run([sys.executable, "-m", "theindex", "--db", str(db_path), "mcp"], input="\n".join(lines) + "\n",
                          capture_output=True, text=True, env=env, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    out = [json.loads(line) for line in proc.stdout.splitlines()]
    for msg in out:
        assert msg["jsonrpc"] == "2.0" and ("result" in msg) != ("error" in msg)
    return out, proc.stderr


class TestMcp(QueryCase):
    def setUp(self):
        super().setUp()
        self.add_file("annual_budget_2025.pdf", title="Budget")
        self.conn.close()

    def test_session(self):
        init = {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}
        out, err = serve(self.path, [
            rpc(1, "initialize", init),
            rpc(2, "initialize", {**init, "protocolVersion": "1999-01-01"}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            rpc(3, "ping"),
            rpc(4, "tools/list"),
            rpc(5, "tools/call", {"name": "find", "arguments": {"words": ["budget"]}}),
            rpc(6, "tools/call", {"name": "nope", "arguments": {}}),
            rpc(20, "tools/call", {"name": "find", "arguments": {"words": "budget"}}),
            "{not json",
            rpc(7, "no/such"),
            rpc(8, "tools/call", {"name": "find", "arguments": {}}),
            rpc(9, "tools/call", {"arguments": {}}),
        ])
        self.assertEqual(err, "")
        by_id = {m["id"]: m for m in out}
        self.assertEqual(len(out), 11)   # no reply to the notification
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(by_id[2]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(by_id[1]["result"]["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "the-index")
        self.assertIn("untrusted", by_id[1]["result"]["instructions"])
        self.assertEqual(by_id[3]["result"], {})
        tools = by_id[4]["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["find", "tree", "projects", "folder", "changes", "describe"])
        self.assertTrue(all(t["inputSchema"]["type"] == "object" and t["description"] for t in tools))
        self.assertEqual(tools[0]["inputSchema"]["required"], ["words"])
        self.assertEqual(tools[0]["inputSchema"]["properties"]["limit"]["maximum"], 500)
        found = by_id[5]["result"]
        self.assertEqual(by_id[20]["result"]["structuredContent"], found["structuredContent"])
        self.assertFalse(found["isError"])
        self.assertEqual(json.loads(found["content"][0]["text"]), found["structuredContent"])
        self.conn = db.open(self.path)
        self.assertEqual(found["structuredContent"], query.find(self.conn, {"words": ["budget"]}))
        self.assertTrue(found["structuredContent"]["results"])
        self.assertTrue(by_id[6]["result"]["isError"])
        parse = next(m for m in out if m["id"] is None)
        self.assertEqual(parse["error"]["code"], -32700)
        self.assertEqual(by_id[7]["error"]["code"], -32601)
        self.assertTrue(by_id[8]["result"]["isError"])
        self.assertEqual(by_id[9]["error"]["code"], -32602)

    def test_missing_database(self):
        out, _ = serve(self.path.parent / "absent.db", [rpc(1, "tools/call", {"name": "projects", "arguments": {}})])
        self.assertTrue(out[0]["result"]["isError"])
        self.assertIn("no database yet", out[0]["result"]["content"][0]["text"])
