# SPDX-License-Identifier: MIT
"""`serve`: live page, search API, review/declare POSTs, origin and content-type guards, clean shutdown."""
import http.client
import json
import threading

from test_html import embedded
from test_pages import PagesCase, seed_files

from theindex import db
from theindex.pages import serve


class TestServe(PagesCase):
    def setUp(self):
        super().setUp()
        self.fill()
        self.server = serve.make_server(self.path, 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive())

    def call(self, method, path, body=None, headers=None):
        """Request with the token (header for /api/, ?t= elsewhere); raw() sends exactly what it is given."""
        headers = {serve.TOKEN_HEADER: self.server.token, **(headers or {})}
        if not path.startswith("/api/"):
            path += ("&" if "?" in path else "?") + "t=" + self.server.token
        return self.raw(method, path, body, headers)

    def raw(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def post(self, path, obj, token=True, **extra):
        headers = {"Content-Type": "application/json", **extra}
        send = self.call if token else self.raw
        status, data = send("POST", path, json.dumps(obj), headers)
        return status, json.loads(data)

    def test_page_is_live_and_flagged(self):
        status, data = self.call("GET", "/")
        self.assertEqual(status, 200)
        d = embedded(data.decode())
        self.assertTrue(d["served"])
        self.assertTrue(d["model"]["changes"])

    def test_token_required(self):
        status, data = self.raw("GET", "/")
        self.assertEqual(status, 403)
        self.assertIn(b"the-index serve", data)
        self.assertEqual(self.raw("GET", "/?t=wrong")[0], 403)
        self.assertEqual(self.raw("GET", "/docs/AI_GUIDE.md")[0], 403)
        self.assertEqual(self.raw("GET", "/api/search?q=crontab")[0], 403)
        self.assertEqual(self.raw("GET", "/api/search?q=crontab", None, {serve.TOKEN_HEADER: "x"})[0], 403)
        cid = self.one("SELECT id FROM v_changes_open LIMIT 1")
        self.assertEqual(self.post("/api/review", {"change_id": cid, "by": "a"}, token=False)[0], 403)
        self.assertEqual(self.post("/api/declare", {"key": "k"}, token=False)[0], 403)
        self.assertEqual(self.one("SELECT count(*) FROM v_changes_open WHERE id = ?", (cid,)), 1)

    def test_security_headers_on_every_response(self):
        for path in ("/", "/api/search?q=crontab", "/docs/nope.md", "/nope"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("GET", path + ("&" if "?" in path else "?") + "t=" + self.server.token,
                         headers={serve.TOKEN_HEADER: self.server.token})
            resp = conn.getresponse()
            resp.read()
            for name, value in serve.SECURITY_HEADERS.items():
                self.assertEqual(resp.getheader(name), value, (path, name))
            conn.close()
        self.assertIn("frame-ancestors 'none'", serve.SECURITY_HEADERS["Content-Security-Policy"])

    def test_content_length_rules(self):
        base = {"Content-Type": "application/json", serve.TOKEN_HEADER: self.server.token}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest("POST", "/api/review")
        for name, value in base.items():
            conn.putheader(name, value)
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 411)
        conn.close()
        self.assertEqual(self.raw("POST", "/api/review", "{}", {**base, "Content-Length": "-5"})[0], 400)
        self.assertEqual(self.raw("POST", "/api/review", "{}", {**base, "Content-Length": "x"})[0], 400)
        self.assertEqual(serve.Handler.timeout, 10)

    def test_page_embeds_token(self):
        d = embedded(self.call("GET", "/")[1].decode())
        self.assertEqual(d["token"], self.server.token)

    def test_search_api(self):
        status, data = self.call("GET", "/api/search?q=crontab%3Ac&limit=5")
        hits = json.loads(data)
        self.assertEqual(status, 200)
        self.assertIn("crontab:c", [h["key"] for h in hits])
        self.assertEqual(self.call("GET", "/api/search?q=")[0], 400)

    def test_find_api_shape_cap_and_errors(self):
        seed_files(self.conn)
        status, data = self.call("GET", "/api/find?q=tomato%20plan&limit=2")
        out = json.loads(data)
        self.assertEqual(status, 200)
        self.assertEqual((out["schema_version"], len(out["results"]), out["more"]), (1, 2, 1))
        self.assertEqual({"type", "device", "path", "name", "title"} - set(out["results"][0]), set())
        out = json.loads(self.call("GET", "/api/find?q=garden&limit=9999")[1])
        self.assertEqual(out["query"]["limit"], serve.FIND_LIMIT)
        self.assertEqual(self.call("GET", "/api/find?q=tomato&limit=0")[0], 200)
        for bad in ("/api/find", "/api/find?q=", "/api/find?q=x&limit=abc", "/api/find?q=" + "a+" * 13):
            status, data = self.call("GET", bad)
            self.assertEqual((status, json.loads(data)["ok"]), (400, False), bad)
        self.assertIn(self.call("GET", "/api/find?q=%22%28%2A")[0], (200, 400))   # odd input never 500s
        self.assertEqual(self.raw("GET", "/api/find?q=garden")[0], 403)
        self.assertEqual(self.post("/api/find", {"q": "x"})[0], 404)

    def test_served_pages_carry_the_finder_and_no_index(self):
        text = self.call("GET", "/")[1].decode()
        self.assertIn("theIndexFinder(D)", text)
        self.assertNotIn("finder", embedded(text))
        self.assertIn('theIndexFinder({"served"', self.call("GET", "/docs/nope.md")[1].decode())

    def test_review_marks_change(self):
        cid = self.one("SELECT id FROM v_changes_open ORDER BY id LIMIT 1")
        status, body = self.post("/api/review", {"change_id": cid, "by": "alice", "note": "ok"})
        self.assertEqual((status, body["ok"]), (200, True))
        self.assertEqual(self.one("SELECT reviewed_by FROM v_change WHERE id = ?", (cid,)), "alice")
        status, body = self.post("/api/review", {"change_id": cid, "by": "alice"})
        self.assertEqual((status, body["ok"]), (400, False))
        self.assertEqual(self.post("/api/review", {"change_id": cid})[0], 400)

    def test_declare(self):
        status, body = self.post("/api/declare", {"key": "crontab:*", "reason": "planned", "by": "alice",
                                                  "change": "modified", "expires": "1d", "kind": "job"})
        self.assertEqual((status, body["ok"]), (200, True))
        self.assertEqual(self.post("/api/declare", {"key": "x"})[0], 400)
        self.assertEqual(self.post("/api/declare", {"key": "x", "reason": "r", "by": "a", "change": "bogus"})[0], 400)

    def test_origin_and_content_type_guards(self):
        cid = self.one("SELECT id FROM v_changes_open LIMIT 1")
        self.assertEqual(self.post("/api/review", {"change_id": cid, "by": "a"}, Origin="http://evil.example")[0], 403)
        ok = f"http://localhost:{self.port}"
        self.assertEqual(self.post("/api/review", {"change_id": cid, "by": "a"}, Origin=ok)[0], 200)
        status, _ = self.call("POST", "/api/review", "change_id=1&by=a",
                              {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertIn(status, (400, 415))
        self.assertEqual(self.call("POST", "/api/review", "{}", {"Host": "evil.example",
                                                                 "Content-Type": "application/json"})[0], 403)

    def test_docs_routes(self):
        status, data = self.call("GET", "/docs/AI_GUIDE.md")
        self.assertIn(status, (200, 404))
        if status == 200:
            self.assertIn(b"<h1>", data)
        for bad in ("/docs/../x", "/docs/..%2F..%2Fetc%2Fpasswd", "/docs/nope.md", "/docs/ai_guide.md"):
            self.assertEqual(self.call("GET", bad)[0], 404, bad)

    def test_connection_per_request_sees_new_data(self):
        db.init(self.path).execute("UPDATE change SET reviewed_by='bob', reviewed_at='2026-01-01T00:00:00Z' "
                                   "WHERE id = (SELECT min(id) FROM change)")
        d = embedded(self.call("GET", "/")[1].decode())
        self.assertEqual(len(d["model"]["changes"]), self.one("SELECT count(*) FROM v_changes_open"))
