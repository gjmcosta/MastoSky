"""Testes unitários dos parsers do MastoSky. Sem rede e sem config.json."""
import json
import os
import stat
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402


class CleanTests(unittest.TestCase):
    def test_removes_invisible_spans(self):
        h = '<p>olá <span class="invisible">https://</span>exemplo</p>'
        self.assertEqual(app.clean(h), "olá exemplo")

    def test_keeps_br(self):
        self.assertEqual(app.clean("a<br>b"), "a<br>b")

    def test_only_http_links(self):
        out = app.clean('<a href="javascript:alert(1)">x</a><a href="https://ok.pt">y</a>')
        self.assertNotIn("javascript:", out)
        self.assertIn('href="https://ok.pt"', out)

    def test_escapes_html(self):
        self.assertEqual(app.clean("<p>&lt;script&gt;</p>"), "&lt;script&gt;")

    def test_strip_quote_inline(self):
        h = '<p class="quote-inline">RE: <a href="https://x.pt">x</a></p><p>texto</p>'
        self.assertEqual(app.clean(h, strip_quote_inline=True), "texto")


class LinkifyTests(unittest.TestCase):
    def test_escapes_and_links(self):
        out = app.linkify("<b> https://a.pt/x\nfim")
        self.assertIn("&lt;b&gt;", out)
        self.assertIn('<a href="https://a.pt/x"', out)
        self.assertIn("<br>", out)


class BskyEmbedTests(unittest.TestCase):
    def test_images(self):
        m, q = app.extract_bsky_embed({
            "$type": "app.bsky.embed.images#view",
            "images": [{"fullsize": "https://f/1", "thumb": "https://t/1", "alt": "a"}]})
        self.assertEqual(m, [{"type": "image", "url": "https://f/1", "thumb": "https://t/1", "alt": "a"}])
        self.assertIsNone(q)

    def test_video(self):
        m, _ = app.extract_bsky_embed({
            "$type": "app.bsky.embed.video#view",
            "playlist": "https://v/p.m3u8", "thumbnail": "https://v/t.jpg"})
        self.assertEqual(m[0]["type"], "video")
        self.assertEqual(m[0]["url"], "https://v/p.m3u8")

    def test_external(self):
        m, _ = app.extract_bsky_embed({
            "$type": "app.bsky.embed.external#view",
            "external": {"uri": "https://e.pt", "title": "T", "description": "D", "thumb": None}})
        self.assertEqual(m[0]["type"], "external")
        self.assertEqual(m[0]["title"], "T")

    def _record(self):
        return {
            "$type": "app.bsky.embed.record#viewRecord",
            "uri": "at://did:plc:x/app.bsky.feed.post/abc",
            "author": {"handle": "a.bsky.social", "displayName": "A"},
            "value": {"text": "citado"},
            "embeds": [{"$type": "app.bsky.embed.images#view",
                        "images": [{"fullsize": "https://f/2", "thumb": "https://t/2"}]}]}

    def test_record(self):
        m, q = app.extract_bsky_embed({"$type": "app.bsky.embed.record#view", "record": self._record()})
        self.assertEqual(m, [])
        self.assertEqual(q["name"], "A")
        self.assertEqual(q["media"][0]["url"], "https://f/2")

    def test_record_with_media(self):
        m, q = app.extract_bsky_embed({
            "$type": "app.bsky.embed.recordWithMedia#view",
            "media": {"$type": "app.bsky.embed.images#view",
                      "images": [{"fullsize": "https://f/3", "thumb": "https://t/3"}]},
            "record": {"record": self._record()}})
        self.assertEqual(m[0]["url"], "https://f/3")
        self.assertEqual(q["handle"], "@a.bsky.social")

    def test_quote_not_found_and_blocked(self):
        self.assertIn("indispon", app.parse_bsky_quote({"$type": "app.bsky.embed.record#viewNotFound"})["name"])
        self.assertIn("bloqueada", app.parse_bsky_quote({"$type": "app.bsky.embed.record#viewBlocked"})["name"])

    def test_quote_wrapped(self):
        q = app.parse_bsky_quote({"record": self._record()})
        self.assertEqual(q["name"], "A")

    def test_quote_none(self):
        self.assertIsNone(app.parse_bsky_quote(None))
        self.assertIsNone(app.parse_bsky_quote({"$type": "outro"}))


class MastoQuoteTests(unittest.TestCase):
    def _status(self, **kw):
        s = {"account": {"display_name": "M", "username": "m", "acct": "m@x.pt", "avatar": "https://a"},
             "content": '<p class="quote-inline">RE: <a href="https://x">x</a></p><p>citado</p>',
             "created_at": "2026-01-01T00:00:00.000Z", "url": "https://x/1", "media_attachments": []}
        s.update(kw)
        return s

    def test_accepted(self):
        q = app.parse_masto_quote({"quote": {"state": "accepted", "quoted_status": self._status()}})
        self.assertEqual(q["handle"], "@m@x.pt")
        self.assertEqual(q["html"], "citado")

    def test_pending_ok_rejected_none(self):
        self.assertIsNotNone(app.parse_masto_quote({"quote": {"state": "pending", "quoted_status": self._status()}}))
        self.assertIsNone(app.parse_masto_quote({"quote": {"state": "rejected", "quoted_status": self._status()}}))

    def test_direct_quoted_status(self):
        self.assertIsNotNone(app.parse_masto_quote({"quoted_status": self._status()}))

    def test_re_prefix_removed(self):
        q = app.parse_masto_quote({"quote": {"state": "accepted", "quoted_status": self._status(
            content='<p>RE: <a href="https://x">x</a></p><p>corpo</p>')}})
        self.assertEqual(q["html"], "corpo")

    def test_no_quote(self):
        self.assertIsNone(app.parse_masto_quote({"content": "x"}))


class MultipartTests(unittest.TestCase):
    def test_body(self):
        body, ctype = app.multipart_encode({"description": "d"}, {"file": ("a.png", b"\x89PNG", "image/png")})
        boundary = ctype.split("boundary=")[1].encode()
        self.assertTrue(body.startswith(b"--" + boundary))
        self.assertTrue(body.rstrip().endswith(b"--" + boundary + b"--"))
        self.assertIn(b'name="description"', body)
        self.assertIn(b'filename="a.png"', body)
        self.assertIn(b"\x89PNG", body)


class ItemTests(unittest.TestCase):
    KEYS = {"network", "name", "handle", "avatar", "html", "time", "boosted_by", "reply_to", "media",
            "quote", "replies", "boosts", "likes", "url", "ref", "is_reply"}

    def test_bsky_item(self):
        p = {"uri": "at://did:plc:x/app.bsky.feed.post/abc", "cid": "c",
             "author": {"handle": "a.bsky.social", "displayName": "A", "avatar": "https://av"},
             "record": {"text": "olá", "createdAt": "2026-01-01T00:00:00.000Z"},
             "replyCount": 1, "repostCount": 2, "likeCount": 3}
        it = app.Bsky({"handle": "h", "app_password": "p"}).item(p)
        self.assertTrue(self.KEYS <= set(it))
        self.assertEqual(it["network"], "bluesky")
        self.assertEqual(it["ref"]["uri"], p["uri"])
        self.assertEqual(it["likes"], 3)

    def test_masto_item(self):
        st = {"id": "1", "account": {"display_name": "M", "username": "m", "acct": "m", "avatar": "https://a"},
              "content": "<p>olá</p>", "created_at": "2026-01-01T00:00:00.000Z", "url": "https://x/1",
              "media_attachments": [{"type": "image", "url": "https://i", "preview_url": "https://p"}],
              "replies_count": 1, "reblogs_count": 2, "favourites_count": 3}
        it = app.Masto({"instance": "https://x", "token": "t"}).item(st)
        self.assertTrue(self.KEYS <= set(it))
        self.assertEqual(it["ref"], {"id": "1"})
        self.assertEqual(it["media"][0]["type"], "image")


class SafeUrlTests(unittest.TestCase):
    BAD = ["javascript:alert(1)", "data:text/html,<script>1</script>", "//evil.example/x", "", None, 5, "https://"]

    def test_safe_url(self):
        for b in self.BAD:
            self.assertIsNone(app.safe_url(b), b)
        self.assertEqual(app.safe_url(" https://ok.pt/a "), "https://ok.pt/a")
        self.assertEqual(app.safe_url("http://ok.pt"), "http://ok.pt")

    def test_media_sanitised(self):
        self.assertIsNone(app.safe_media({"type": "image", "url": "javascript:1", "thumb": None}))
        self.assertIsNone(app.safe_media({"type": "external", "url": "data:x", "thumb": "https://t"}))
        m = app.safe_media({"type": "image", "url": "javascript:1", "thumb": "https://t"})
        self.assertEqual(m["url"], "https://t")
        m = app.safe_media({"type": "external", "url": "https://e", "thumb": "javascript:1"})
        self.assertIsNone(m["thumb"])

    def test_masto_item_fields(self):
        evil = "javascript:alert(1)"
        st = {"id": "1", "account": {"display_name": "M", "username": "m", "acct": "m", "avatar": evil},
              "content": "x", "created_at": "2026-01-01T00:00:00.000Z", "url": evil,
              "media_attachments": [{"type": "image", "url": evil, "preview_url": evil}],
              "card": {"url": evil, "image": evil}}
        it = app.Masto({"instance": "https://x", "token": "t"}).item(st)
        self.assertIsNone(it["avatar"])
        self.assertIsNone(it["url"])
        self.assertEqual(it["media"], [])

    def test_bsky_item_fields(self):
        evil = "javascript:alert(1)"
        p = {"uri": "at://did:plc:x/app.bsky.feed.post/abc", "cid": "c",
             "author": {"handle": "a.bsky.social", "avatar": evil},
             "record": {"text": "x", "createdAt": "2026-01-01T00:00:00.000Z"},
             "embed": {"$type": "app.bsky.embed.external#view",
                       "external": {"uri": evil, "thumb": evil, "title": "t"}}}
        it = app.Bsky({"handle": "h", "app_password": "p"}).item(p)
        self.assertIsNone(it["avatar"])
        self.assertEqual(it["media"], [])


class ConfigPermsTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "permissões POSIX")
    def test_write_config_is_0600(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text("{}")
            os.chmod(path, 0o644)
            app.write_config({"a": 1}, path)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            os.chmod(path, 0o666)
            app.secure_config_perms(path)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


class SecurityHeadersTests(unittest.TestCase):
    def _handler(self, host, origin=None):
        import io
        h = object.__new__(app.H)
        h.headers = {"Host": host}
        if origin:
            h.headers["Origin"] = origin
        h.sent = []
        h.wfile = io.BytesIO()
        h.send_response = lambda code: h.sent.append(("code", code))
        h.send_header = lambda k, v: h.sent.append((k, v))
        h.end_headers = lambda: None
        return h

    def test_send_adds_security_headers(self):
        h = self._handler("127.0.0.1:%d" % app.PORT)
        h.send(200, {"ok": True})
        names = dict(h.sent)
        self.assertEqual(names["X-Content-Type-Options"], "nosniff")
        self.assertEqual(names["Referrer-Policy"], "no-referrer")
        self.assertEqual(names["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", names["Content-Security-Policy"])
        self.assertNotIn("0.0.0.0", names["Content-Security-Policy"])

    def test_allowed_checks_host_and_origin(self):
        p = app.PORT
        self.assertTrue(self._handler("127.0.0.1:%d" % p).allowed())
        self.assertTrue(self._handler("localhost:%d" % p, "http://localhost:%d" % p).allowed())
        self.assertFalse(self._handler("evil.example").allowed())
        self.assertFalse(self._handler("127.0.0.1:%d" % p, "http://evil.example").allowed())

    def test_hls_is_vendored(self):
        self.assertTrue((app.DIR / "vendor" / "hls.min.js").exists())
        self.assertNotIn("cdn.jsdelivr", (app.DIR / "index.html").read_text())


class PostHandlerTests(unittest.TestCase):
    def _post(self, path, body, length=None):
        import io
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        h = object.__new__(app.H)
        h.path = path
        h.headers = {"Host": "127.0.0.1:%d" % app.PORT,
                     "Content-Length": str(len(raw)) if length is None else length}
        h.rfile = io.BytesIO(raw)
        h.wfile = io.BytesIO()
        h.sent = []
        h.send_response = lambda code: h.sent.append(("code", code))
        h.send_header = lambda k, v: h.sent.append((k, v))
        h.end_headers = lambda: None
        h.do_POST()
        code = [v for k, v in h.sent if k == "code"][0]
        return code, json.loads(h.wfile.getvalue())

    def setUp(self):
        from unittest import mock
        self.client = mock.Mock()
        p = mock.patch.dict(app.CLIENTS, {"bluesky": self.client}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_invalid_json(self):
        code, r = self._post("/api/post", b"{nao e json")
        self.assertEqual(code, 400)
        self.assertEqual(r["error"], "JSON inválido")

    def test_json_not_dict(self):
        self.assertEqual(self._post("/api/post", b"[1,2]")[0], 400)

    def test_body_too_large(self):
        code, _ = self._post("/api/post", b"{}", length=str(app.MAX_BODY + 1))
        self.assertEqual(code, 413)

    def test_bad_content_length(self):
        self.assertEqual(self._post("/api/post", b"{}", length="abc")[0], 400)

    def test_unknown_target(self):
        code, r = self._post("/api/post", {"text": "x", "targets": ["mastodon"]})
        self.assertEqual(code, 400)
        self.assertIn("mastodon", r["error"])

    def test_no_targets(self):
        self.assertEqual(self._post("/api/post", {"text": "x", "targets": []})[0], 400)
        self.assertEqual(self._post("/api/post", {"text": "x", "targets": "bluesky"})[0], 400)

    def test_invalid_base64(self):
        code, _ = self._post("/api/post", {"text": "x", "targets": ["bluesky"],
                                           "images": [{"data": "data:image/png;base64,@@@"}]})
        self.assertEqual(code, 400)
        self.client.post.assert_not_called()

    def test_bad_images_shape(self):
        self.assertEqual(self._post("/api/post", {"targets": ["bluesky"], "images": "x"})[0], 400)
        self.assertEqual(self._post("/api/post", {"targets": ["bluesky"], "images": [5]})[0], 400)

    def test_valid_post(self):
        code, r = self._post("/api/post", {"text": " olá ", "targets": ["bluesky"]})
        self.assertEqual((code, r), (200, {"bluesky": "ok"}))
        self.assertEqual(self.client.post.call_args[0][0], "olá")

    def test_unexpected_error_is_generic_500(self):
        from unittest import mock
        with mock.patch.object(app.H, "_read_json", side_effect=RuntimeError("segredo-token")):
            code, r = self._post("/api/post", {})
        self.assertEqual(code, 500)
        self.assertNotIn("segredo", json.dumps(r))


class HttpErrorTests(unittest.TestCase):
    def _http_error(self, code, retry_after=None, body=b"x"):
        import io
        import urllib.error
        from email.message import Message
        hdrs = Message()
        if retry_after is not None:
            hdrs["Retry-After"] = str(retry_after)
        return urllib.error.HTTPError("https://x.pt/a", code, "err", hdrs, io.BytesIO(body))

    def test_http_error_keeps_code_prefix(self):
        from unittest import mock
        with mock.patch("app.urllib.request.urlopen", side_effect=self._http_error(401, body=b"ExpiredToken")):
            with self.assertRaises(app.ApiError) as cm:
                app.http("GET", "https://x.pt/a", token="SEGREDO")
        self.assertTrue(str(cm.exception).startswith("401"))
        self.assertIn("ExpiredToken", str(cm.exception))
        self.assertEqual(cm.exception.status, 401)
        self.assertNotIn("SEGREDO", str(cm.exception))
        self.assertIsInstance(cm.exception, RuntimeError)

    def test_429_short_retry_after_retries_get(self):
        from unittest import mock
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b'{"a": 1}'
        with mock.patch("app.urllib.request.urlopen", side_effect=[self._http_error(429, 2), ok]) as u, \
                mock.patch("app.time.sleep") as sl:
            self.assertEqual(app.http("GET", "https://x.pt/a"), {"a": 1})
        sl.assert_called_once_with(2)
        self.assertEqual(u.call_count, 2)

    def test_429_long_retry_after_propagates(self):
        from unittest import mock
        with mock.patch("app.urllib.request.urlopen", side_effect=self._http_error(429, 120)), \
                mock.patch("app.time.sleep") as sl:
            with self.assertRaises(app.ApiError) as cm:
                app.http("GET", "https://x.pt/a")
        sl.assert_not_called()
        self.assertEqual(cm.exception.retry_after, 120)
        self.assertIn("120", str(cm.exception))

    def test_429_without_retry_after_and_post_not_retried(self):
        from unittest import mock
        with mock.patch("app.urllib.request.urlopen", side_effect=self._http_error(429)) as u:
            with self.assertRaises(app.ApiError) as cm:
                app.http("GET", "https://x.pt/a")
        self.assertIsNone(cm.exception.retry_after)
        self.assertEqual(u.call_count, 1)
        with mock.patch("app.urllib.request.urlopen", side_effect=self._http_error(429, 1)) as u:
            with self.assertRaises(app.ApiError):
                app.http("POST", "https://x.pt/a", data={})
        self.assertEqual(u.call_count, 1)

    def test_url_error_and_timeout(self):
        import socket
        import urllib.error
        from unittest import mock
        with mock.patch("app.urllib.request.urlopen", side_effect=urllib.error.URLError("dns")):
            with self.assertRaises(app.ApiError) as cm:
                app.http("GET", "https://bsky.social/x")
        self.assertIn("Sem ligação a bsky.social", str(cm.exception))
        with mock.patch("app.urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            with self.assertRaises(app.ApiError) as cm:
                app.http("GET", "https://bsky.social/x")
        self.assertIn("Sem ligação a bsky.social", str(cm.exception))


class BskySessionTests(unittest.TestCase):
    def _client(self):
        return app.Bsky({"handle": "h.bsky.social", "app_password": "pw"})

    def _fake_http(self, calls, refresh_ok=True, expire_first=True):
        state = {"expired": expire_first}

        def fake(method, url, data=None, token=None, headers=None):
            calls.append((url.rsplit("/", 1)[-1].rsplit(".", 1)[-1], token))
            if url.endswith("createSession"):
                return {"accessJwt": "access-%d" % len(calls), "refreshJwt": "refresh-1", "did": "did:plc:me"}
            if url.endswith("refreshSession"):
                if not refresh_ok:
                    raise app.ApiError("400: bad refresh", status=400)
                return {"accessJwt": "renewed", "refreshJwt": "refresh-2", "did": "did:plc:me"}
            if state["expired"] and token != "renewed" and not token.startswith("access-new"):
                state["expired"] = False
                raise app.ApiError('400: {"error":"ExpiredToken"}', status=400)
            return {"ok": True, "token": token}
        return fake

    def test_refresh_used_instead_of_create_session(self):
        from unittest import mock
        calls = []
        c = self._client()
        with mock.patch("app.http", side_effect=self._fake_http(calls)):
            r = c.call("GET", "app.bsky.feed.getTimeline")
        names = [n for n, _ in calls]
        self.assertEqual(names, ["createSession", "getTimeline", "refreshSession", "getTimeline"])
        self.assertEqual(names.count("createSession"), 1)
        self.assertEqual(calls[2][1], "refresh-1")  # refreshJwt usado como bearer
        self.assertEqual(r["token"], "renewed")
        self.assertEqual(c.refresh_jwt, "refresh-2")

    def test_falls_back_to_create_session_if_refresh_fails(self):
        from unittest import mock
        calls = []
        c = self._client()
        with mock.patch("app.http", side_effect=self._fake_http(calls, refresh_ok=False)):
            c.call("GET", "app.bsky.feed.getTimeline")
        names = [n for n, _ in calls]
        self.assertEqual(names, ["createSession", "getTimeline", "refreshSession", "createSession", "getTimeline"])

    def test_upload_blob_also_renews(self):
        from unittest import mock
        calls = []
        c = self._client()
        fake = self._fake_http(calls)
        with mock.patch("app.http", side_effect=lambda *a, **k: dict(fake(*a, **k), blob={"ref": "b"})):
            self.assertEqual(c.upload_blob(b"x", "image/png"), {"ref": "b"})
        self.assertIn("refreshSession", [n for n, _ in calls])

    def test_non_auth_errors_propagate(self):
        from unittest import mock
        c = self._client()
        c.jwt, c.did = "tok", "did:plc:me"
        with mock.patch("app.http", side_effect=app.ApiError("500: boom", status=500)) as h:
            with self.assertRaises(app.ApiError):
                c.call("GET", "x")
        self.assertEqual(h.call_count, 1)


class ParseTimeTests(unittest.TestCase):
    def test_formats(self):
        from datetime import datetime, timezone
        ref = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        for s in ("2026-01-02T03:04:05Z", "2026-01-02T03:04:05+00:00", "2026-01-02T03:04:05.000Z",
                  "2026-01-02T03:04:05.000000+00:00", "2026-01-02T04:04:05+01:00", "2026-01-02T03:04:05"):
            self.assertEqual(app.parse_time(s), ref, s)

    def test_fractions(self):
        a = app.parse_time("2026-01-02T03:04:05.5Z")
        b = app.parse_time("2026-01-02T03:04:05.123456789Z")
        self.assertEqual(a.microsecond, 500000)
        self.assertEqual(b.microsecond, 123456)

    def test_invalid_is_epoch(self):
        for s in ("", "ontem", None, 5, "2026-13-45T99:99:99Z"):
            self.assertEqual(app.parse_time(s).year, 1970, s)

    def test_sort_mixed_networks(self):
        items = [
            {"id": "bsky-z", "time": "2026-01-02T03:04:06Z"},
            {"id": "masto-frac", "time": "2026-01-02T03:04:05.900Z"},
            {"id": "bsky-offset", "time": "2026-01-02T05:00:00+01:00"},  # = 04:00:00Z
            {"id": "bad", "time": "lixo"},
            {"id": "masto-old", "time": "2026-01-01T00:00:00.000Z"},
        ]
        self.assertEqual([i["id"] for i in app.sort_items(items)],
                         ["bsky-offset", "bsky-z", "masto-frac", "masto-old", "bad"])

    def test_bsky_item_prefers_indexed_at(self):
        p = {"uri": "at://did:plc:x/app.bsky.feed.post/abc", "cid": "c",
             "author": {"handle": "a.bsky.social"}, "indexedAt": "2026-01-02T00:00:00Z",
             "record": {"text": "x", "createdAt": "2099-01-01T00:00:00Z"}}
        it = app.Bsky({"handle": "h", "app_password": "p"}).item(p)
        self.assertEqual(it["time"], "2026-01-02T00:00:00Z")


class ThreadSafetyTests(unittest.TestCase):
    def test_concurrent_requests_login_once(self):
        import threading
        import time as _time
        from unittest import mock
        calls = []

        def fake(method, url, data=None, token=None, headers=None):
            calls.append(url.rsplit(".", 1)[-1])
            if url.endswith("createSession"):
                _time.sleep(0.05)  # alarga a janela de corrida
                return {"accessJwt": "a", "refreshJwt": "r", "did": "did:plc:me"}
            return {"ok": True}
        c = app.Bsky({"handle": "h", "app_password": "p"})
        with mock.patch("app.http", side_effect=fake):
            ts = [threading.Thread(target=c.call, args=("GET", "x")) for _ in range(8)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        self.assertEqual(calls.count("createSession"), 1)

    def test_concurrent_renew_refreshes_once(self):
        import threading
        import time as _time
        from unittest import mock
        calls = []

        def fake(method, url, data=None, token=None, headers=None):
            calls.append(url.rsplit(".", 1)[-1])
            if url.endswith("refreshSession"):
                _time.sleep(0.05)
                return {"accessJwt": "new", "refreshJwt": "r2", "did": "did:plc:me"}
            if token == "old":
                raise app.ApiError('400: {"error":"ExpiredToken"}', status=400)
            return {"ok": True}
        c = app.Bsky({"handle": "h", "app_password": "p"})
        c.jwt, c.refresh_jwt, c.did = "old", "r1", "did:plc:me"
        with mock.patch("app.http", side_effect=fake):
            ts = [threading.Thread(target=c.call, args=("GET", "x")) for _ in range(8)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        self.assertEqual(calls.count("refreshSession"), 1)
        self.assertNotIn("createSession", calls)

    def test_masto_parent_cache_concurrent(self):
        import threading
        from unittest import mock
        m = app.Masto({"instance": "https://x.pt", "token": "t"})
        with mock.patch.object(app.Masto, "call", side_effect=lambda *a, **k: {"id": "1"}):
            ts = [threading.Thread(target=m.parent, args=(str(i % 700),)) for i in range(1400)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        self.assertLessEqual(len(m.cache), 501)


class CleanQuoteInlineTests(unittest.TestCase):
    def test_self_closed_br_inside_quote_inline(self):
        h = '<p class="quote-inline">RE: <a href="https://x">x</a><br/></p><p>texto</p>'
        self.assertEqual(app.clean(h, strip_quote_inline=True), "texto")

    def test_unclosed_br_inside_quote_inline(self):
        h = '<p class="quote-inline">RE: <a href="https://x">x</a><br></p><p>texto</p>'
        self.assertEqual(app.clean(h, strip_quote_inline=True), "texto")

    def test_nested_tags_inside_quote_inline(self):
        h = '<p class="quote-inline"><span>RE:</span> <a href="https://x"><span>x</span></a></p><p>depois</p>'
        self.assertEqual(app.clean(h, strip_quote_inline=True), "depois")

    def test_br_self_closed_outside_is_kept(self):
        self.assertEqual(app.clean("a<br/>b", strip_quote_inline=True), "a<br>b")
        self.assertEqual(app.clean("a<br/>b"), "a<br>b")

    def test_content_after_block_not_swallowed_and_stray_end_tags(self):
        h = '<p class="quote-inline">RE: x</p></span><p>um</p><p>dois</p>'
        self.assertEqual(app.clean(h, strip_quote_inline=True), "um<br><br>dois")

    def test_without_flag_quote_inline_is_kept(self):
        h = '<p class="quote-inline">RE: x</p><p>y</p>'
        self.assertIn("RE: x", app.clean(h))


if __name__ == "__main__":
    unittest.main()
