# SPDX-License-Identifier: MIT
"""`the-index serve`: the page rendered live from the database, plus search and review. 127.0.0.1 only."""
import hmac
import json
import secrets
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .. import db, declare, search
from .. import query as queries
from . import docs, html

HOST = "127.0.0.1"
MAX_BODY = 65536
FIND_LIMIT = 50
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
                               "script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'none'",
    "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
TOKEN_HEADER = "X-The-Index-Token"
NEED_TOKEN = "<p>Open the link printed by <code>the-index serve</code>.</p>"
NO_DOCS = "Documentation is not shipped with this install. It lives in the docs/ folder of the project repository."


def make_server(db_path, port=0):
    """A bound, not yet serving, server. Port 0 picks a free port."""
    try:
        server = ThreadingHTTPServer((HOST, port), Handler)
    except OSError as exc:
        raise ValueError(f"cannot listen on {HOST}:{port}: {exc.strerror or exc}") from exc
    server.daemon_threads = True
    server.db_path = db_path
    server.token = secrets.token_urlsafe(16)
    return server


def run(db_path, port):
    server = make_server(db_path, port)
    print(f"THE INDEX: http://{HOST}:{server.server_address[1]}/?t={server.token}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def review_action(conn, body):
    if not declare.review(conn, int(body.get("change_id", 0)), body.get("by"), body.get("note")):
        raise ValueError("change not found or already reviewed")
    return {"ok": True}


def declare_action(conn, body):
    return {"ok": True, "id": declare.add(conn, declare.from_fields(body))}


POSTS = {"/api/review": review_action, "/api/declare": declare_action}


class Handler(BaseHTTPRequestHandler):
    server_version = "TheIndex"
    timeout = 10

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _fail(self, code, message):
        self._send(code, {"ok": False, "error": message})

    def _origins(self):
        port = self.server.server_address[1]
        return {f"http://{HOST}:{port}", f"http://localhost:{port}"}

    def _host_ok(self):
        return self.headers.get("Host", "") in {o[len("http://"):] for o in self._origins()}

    def _token_ok(self, given):
        return hmac.compare_digest((given or "").encode(), self.server.token.encode())

    def _gate(self, path, query):
        """True when the request may proceed; otherwise the 403 has been sent."""
        if path.startswith("/api/"):
            ok = self._token_ok(self.headers.get(TOKEN_HEADER))
            return ok or self._fail(403, "missing or wrong token")
        if (path == "/" or path.startswith("/docs/")) and not self._token_ok(query.get("t", [""])[0]):
            self._send(403, docs.page("Forbidden", NEED_TOKEN), "text/html")
            return False
        return True

    def do_GET(self):
        if not self._host_ok():
            return self._fail(403, "bad host")
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if not self._gate(url.path, query):
            return
        try:
            with closing(db.connect(self.server.db_path)) as conn:
                if url.path == "/":
                    return self._send(200, html.render(conn, served=True, token=self.server.token), "text/html")
                if url.path == "/api/search":
                    return self._search(conn, query)
                if url.path == "/api/find":
                    return self._find(conn, query)
        except (ValueError, sqlite3.Error) as exc:
            return self._fail(400, str(exc))
        if url.path.startswith("/docs/"):
            return self._doc(url.path[len("/docs/"):])
        self._fail(404, "not found")

    def _search(self, conn, query):
        limit = int(query.get("limit", ["20"])[0])
        self._send(200, search.run(conn, query.get("q", [""]), limit))

    def _find(self, conn, query):
        """The query layer's find envelope, read-only. limit is capped at FIND_LIMIT."""
        words = query.get("q", [""])[0].split()
        if not words or len(words) > 12:
            raise ValueError("q needs 1 to 12 words")
        try:
            limit = int(query.get("limit", ["20"])[0])
        except ValueError:
            raise ValueError("limit must be a number") from None
        out = queries.find(conn, {"words": words, "limit": max(1, min(limit, FIND_LIMIT))})
        if out.get("error"):
            raise ValueError(out["error"])
        self._send(200, out)

    def _doc(self, name):
        text = docs.read(name)
        if text is None:
            body = NO_DOCS if docs.docs_dir() is None else "No such document."
            return self._send(404, docs.page("Not found", f"<p>{body}</p>", self.server.token), "text/html")
        self._send(200, docs.page(name, docs.convert(text), self.server.token), "text/html")

    def do_POST(self):
        origin = self.headers.get("Origin")
        if not self._host_ok() or (origin is not None and origin not in self._origins()):
            return self._fail(403, "origin not allowed")
        if not self._token_ok(self.headers.get(TOKEN_HEADER)):
            return self._fail(403, "missing or wrong token")
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return self._fail(415, "Content-Type must be application/json")
        if self.headers.get("Content-Length") is None:
            return self._fail(411, "Content-Length required")
        action = POSTS.get(urlsplit(self.path).path)
        if action is None:
            return self._fail(404, "not found")
        try:
            body = self._body()
            with closing(db.connect(self.server.db_path)) as conn:
                self._send(200, action(conn, body))
        except (ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as exc:
            self._fail(400, str(exc) or exc.__class__.__name__)

    def _body(self):
        size = int(self.headers.get("Content-Length", "-1"))
        if size < 0:
            raise ValueError("bad Content-Length")
        if size > MAX_BODY:
            raise ValueError("request too large")
        body = json.loads(self.rfile.read(size) or b"{}")
        if not isinstance(body, dict):
            raise TypeError("body must be a JSON object")
        return body
