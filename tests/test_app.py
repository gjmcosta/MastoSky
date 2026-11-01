"""Testes unitários dos parsers do MastoSky. Sem rede e sem config.json."""
import io
import json
import os
import stat
import sys
import unittest
from unittest import mock
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

    def test_invalid_lang(self):
        self.assertEqual(self._post("/api/post", {"text": "x", "targets": ["bluesky"], "lang": "invalid-long"})[0], 400)
        self.assertEqual(self._post("/api/post", {"text": "x", "targets": ["bluesky"], "lang": 123})[0], 400)

    def test_invalid_visibility(self):
        self.assertEqual(self._post("/api/post", {"text": "x", "targets": ["bluesky"], "visibility": "secret"})[0], 400)

    def test_valid_lang_and_visibility(self):
        code, r = self._post("/api/post", {"text": "x", "targets": ["bluesky"], "lang": "pt", "visibility": "unlisted"})
        self.assertEqual(code, 200)
        self.assertEqual(self.client.post.call_args[1].get("lang"), "pt")


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


class FacetsAndRichtextTests(unittest.TestCase):
    def test_byte_span_with_emojis_and_accents(self):
        text = "é 😀 @alice.bsky.social #olá"
        # "é" is 2 bytes (0..2), " " is 1 byte (2..3), "😀" is 4 bytes (3..7), " " is 1 byte (7..8)
        # "@alice.bsky.social" starts at char index 5 -> byte offset 8
        handle_start = text.index("@alice.bsky.social")
        handle_end = handle_start + len("@alice.bsky.social")
        b_start, b_end = app.byte_span(text, handle_start, handle_end)
        self.assertEqual(b_start, 8)
        self.assertEqual(b_end, 8 + len("@alice.bsky.social".encode("utf-8")))
        self.assertEqual(text.encode("utf-8")[b_start:b_end].decode("utf-8"), "@alice.bsky.social")

    def test_linkify_strips_trailing_punctuation(self):
        res = app.linkify("Vê https://exemplo.pt/x., por favor (https://y.pt/fim)!")
        self.assertIn('<a href="https://exemplo.pt/x" target="_blank" rel="noopener noreferrer">https://exemplo.pt/x</a>.,', res)
        self.assertIn('(<a href="https://y.pt/fim" target="_blank" rel="noopener noreferrer">https://y.pt/fim</a>)!', res)

    def test_render_bsky_text_without_facets_uses_linkify(self):
        res = app.render_bsky_text("Vê https://exemplo.pt/aqui", None)
        self.assertIn('<a href="https://exemplo.pt/aqui"', res)

    def test_render_bsky_text_with_facets_and_escaping(self):
        text = "<script>alert(1)</script> @alice.bsky.social #notícias https://link.pt"
        b_text = text.encode("utf-8")
        mention_sub = "@alice.bsky.social".encode("utf-8")
        tag_sub = "#notícias".encode("utf-8")
        link_sub = "https://link.pt".encode("utf-8")

        m_start = b_text.index(mention_sub)
        t_start = b_text.index(tag_sub)
        l_start = b_text.index(link_sub)

        facets = [
            {
                "index": {"byteStart": m_start, "byteEnd": m_start + len(mention_sub)},
                "features": [{"$type": "app.bsky.richtext.facet#mention", "did": "did:plc:123"}]
            },
            {
                "index": {"byteStart": t_start, "byteEnd": t_start + len(tag_sub)},
                "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": "notícias"}]
            },
            {
                "index": {"byteStart": l_start, "byteEnd": l_start + len(link_sub)},
                "features": [{"$type": "app.bsky.richtext.facet#link", "uri": "https://link.pt"}]
            }
        ]

        rendered = app.render_bsky_text(text, facets)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn('<a href="https://bsky.app/profile/did%3Aplc%3A123" target="_blank" rel="noopener noreferrer">@alice.bsky.social</a>', rendered)
        self.assertIn('<a href="https://bsky.app/hashtag/not%C3%ADcias" target="_blank" rel="noopener noreferrer">#notícias</a>', rendered)
        self.assertIn('<a href="https://link.pt" target="_blank" rel="noopener noreferrer">https://link.pt</a>', rendered)

    def test_render_bsky_text_ignores_overlapping_or_invalid_facets(self):
        text = "Hello world"
        facets = [
            {"index": {"byteStart": 0, "byteEnd": 5}, "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": "first"}]},
            {"index": {"byteStart": 3, "byteEnd": 8}, "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": "overlap"}]},
            {"index": {"byteStart": 100, "byteEnd": 200}, "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": "oob"}]},
            {"index": "invalid", "features": []}
        ]
        rendered = app.render_bsky_text(text, facets)
        self.assertIn("hashtag/first", rendered)
        self.assertNotIn("hashtag/overlap", rendered)
        self.assertIn("world", rendered)

    def test_bsky_post_extracts_and_resolves_facets(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"

        calls = []
        def fake_call(method, nsid, data=None, params=None):
            calls.append((method, nsid, data, params))
            if nsid == "com.atproto.identity.resolveHandle":
                if params.get("handle") == "bob.bsky.social":
                    return {"did": "did:plc:bob"}
                raise app.ApiError("404: Not Found")
            return {"uri": "at://did:plc:me/app.bsky.feed.post/123", "cid": "cid123"}

        b.call = fake_call
        post_text = "Olá @bob.bsky.social e @inexistente.com #teste https://exemplo.pt/x"
        b.post(post_text)

        create_calls = [c for c in calls if c[1] == "com.atproto.repo.createRecord"]
        self.assertEqual(len(create_calls), 1)
        rec = create_calls[0][2]["record"]
        facets = rec.get("facets", [])

        # Should have mention for bob, tag for teste, link for exemplo.pt
        types = [f["features"][0]["$type"] for f in facets]
        self.assertIn("app.bsky.richtext.facet#mention", types)
        self.assertIn("app.bsky.richtext.facet#tag", types)
        self.assertIn("app.bsky.richtext.facet#link", types)

        # bob resolved
        mention_facet = next(f for f in facets if f["features"][0]["$type"] == "app.bsky.richtext.facet#mention")
        self.assertEqual(mention_facet["features"][0]["did"], "did:plc:bob")

        # nonexistent mention skipped
        self.assertFalse(any(f["features"][0].get("did") == "did:plc:inexistente" for f in facets))

        # Check handle cache works
        self.assertEqual(b._handle_cache.get("bob.bsky.social"), "did:plc:bob")

    def test_bsky_post_spoiler_no_self_label(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"

        calls = []
        b.call = lambda m, n, d=None, p=None: calls.append((m, n, d, p)) or {}
        b.post("Mensagem secreta", spoiler="Alerta de spoiler")

        self.assertEqual(len(calls), 1)
        rec = calls[0][2]["record"]
        self.assertIn("⚠️ [CW: Alerta de spoiler]\n\nMensagem secreta", rec["text"])
        self.assertNotIn("labels", rec)

    def test_bsky_post_lang(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"
        calls = []
        b.call = lambda m, n, d=None, p=None: calls.append((m, n, d, p)) or {}
        b.post("Olá mundo", lang="pt")
        self.assertEqual(calls[0][2]["record"].get("langs"), ["pt"])

    def test_masto_post_lang_and_visibility(self):
        m = app.Masto({"instance": "https://m.pt", "token": "tok"})
        calls = []
        m.call = lambda mth, pth, data=None, p=None: calls.append((mth, pth, data, p)) or {}
        m.post("Olá mundo", lang="pt", visibility="unlisted")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2].get("language"), "pt")
        self.assertEqual(calls[0][2].get("visibility"), "unlisted")

    def test_bsky_post_native_quote(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"
        calls = []
        b.call = lambda m, n, d=None, p=None: calls.append((m, n, d, p)) or {}
        quote = {
            "network": "bluesky",
            "ref": {"uri": "at://did:plc:bob/app.bsky.feed.post/123", "cid": "cid123"},
            "url": "https://bsky.app/profile/bob/post/123"
        }
        b.post("Comentário sobre o post", quote=quote)
        self.assertEqual(len(calls), 1)
        rec = calls[0][2]["record"]
        self.assertEqual(rec["embed"]["$type"], "app.bsky.embed.record")
        self.assertEqual(rec["embed"]["record"]["uri"], "at://did:plc:bob/app.bsky.feed.post/123")

    def test_bsky_post_cross_network_quote(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"
        calls = []
        b.call = lambda m, n, d=None, p=None: calls.append((m, n, d, p)) or {}
        quote = {
            "network": "mastodon",
            "url": "https://masto.pt/@alice/999",
            "text": "Post original do Mastodon",
            "name": "Alice",
            "handle": "@alice@masto.pt"
        }
        b.post("Vejam este post do Fediverse!", quote=quote)
        self.assertEqual(len(calls), 1)
        rec = calls[0][2]["record"]
        self.assertEqual(rec["embed"]["$type"], "app.bsky.embed.external")
        self.assertEqual(rec["embed"]["external"]["uri"], "https://masto.pt/@alice/999")
        self.assertIn("Alice", rec["embed"]["external"]["title"])
        self.assertIn("Post original", rec["embed"]["external"]["description"])

    def test_masto_post_quote(self):
        m = app.Masto({"instance": "https://m.pt", "token": "tok"})
        calls = []
        m.call = lambda mth, pth, data=None, p=None: calls.append((mth, pth, data, p)) or {}
        quote = {
            "network": "bluesky",
            "url": "https://bsky.app/profile/bob.bsky.social/post/abc"
        }
        m.post("Muito interessante este post:", quote=quote)
        self.assertEqual(len(calls), 1)
        status = calls[0][2]["status"]
        self.assertIn("Muito interessante este post:", status)
        self.assertIn("https://bsky.app/profile/bob.bsky.social/post/abc", status)


class ActionsTests(unittest.TestCase):
    def test_masto_item_and_act(self):
        m = app.Masto({"instance": "https://m.pt", "token": "tok"})
        st = {
            "id": "100", "account": {"username": "alice", "acct": "alice"},
            "content": "<p>oi</p>", "created_at": "2026-01-01T00:00:00Z",
            "favourited": True, "reblogged": False
        }
        item = m.item(st)
        self.assertTrue(item["liked"])
        self.assertFalse(item["boosted"])
        self.assertEqual(item["ref"], {"id": "100"})

        calls = []
        m.call = lambda mth, pth, d=None, p=None: calls.append((mth, pth)) or {}

        m.act("like", {"id": "100"})
        m.act("unlike", {"id": "100"})
        m.act("boost", {"id": "100"})
        m.act("unboost", {"id": "100"})

        self.assertEqual(calls, [
            ("POST", "/api/v1/statuses/100/favourite"),
            ("POST", "/api/v1/statuses/100/unfavourite"),
            ("POST", "/api/v1/statuses/100/reblog"),
            ("POST", "/api/v1/statuses/100/unreblog")
        ])

    def test_bsky_item_and_act(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"

        p = {
            "uri": "at://did:plc:author/app.bsky.feed.post/post1",
            "cid": "cid1",
            "author": {"handle": "alice.bsky.social"},
            "record": {"text": "ola", "createdAt": "2026-01-01T00:00:00Z"},
            "viewer": {
                "like": "at://did:plc:me/app.bsky.feed.like/like123",
                "repost": "at://did:plc:me/app.bsky.feed.repost/repost456"
            }
        }
        item = b.item(p)
        self.assertTrue(item["liked"])
        self.assertTrue(item["boosted"])
        self.assertEqual(item["ref"]["like_uri"], "at://did:plc:me/app.bsky.feed.like/like123")
        self.assertEqual(item["ref"]["repost_uri"], "at://did:plc:me/app.bsky.feed.repost/repost456")

        calls = []
        def fake_call(m, n, d=None, p=None):
            calls.append((m, n, d))
            if n == "com.atproto.repo.createRecord":
                return {"uri": "at://did:plc:me/app.bsky.feed.like/newlike789"}
            return {}

        b.call = fake_call

        res_like = b.act("like", item["ref"])
        self.assertEqual(res_like["uri"], "at://did:plc:me/app.bsky.feed.like/newlike789")
        self.assertEqual(calls[-1][1], "com.atproto.repo.createRecord")
        self.assertEqual(calls[-1][2]["collection"], "app.bsky.feed.like")

        b.act("unlike", item["ref"])
        self.assertEqual(calls[-1][1], "com.atproto.repo.deleteRecord")
        self.assertEqual(calls[-1][2]["rkey"], "like123")
        self.assertEqual(calls[-1][2]["collection"], "app.bsky.feed.like")

        b.act("boost", item["ref"])
        self.assertEqual(calls[-1][1], "com.atproto.repo.createRecord")
        self.assertEqual(calls[-1][2]["collection"], "app.bsky.feed.repost")

        b.act("unboost", item["ref"])
        self.assertEqual(calls[-1][1], "com.atproto.repo.deleteRecord")
        self.assertEqual(calls[-1][2]["rkey"], "repost456")
        self.assertEqual(calls[-1][2]["collection"], "app.bsky.feed.repost")

    def test_delete_and_is_own(self):
        # Mastodon
        m = app.Masto({"instance": "https://m.pt", "token": "tok"})
        calls = []
        def fake_masto_call(mth, pth, data=None, p=None):
            calls.append((mth, pth))
            if pth == "/api/v1/accounts/verify_credentials":
                return {"id": "my_user_id"}
            return {}

        m.call = fake_masto_call

        own_st = {"id": "1", "account": {"id": "my_user_id", "username": "me", "acct": "me"}, "content": "meu"}
        other_st = {"id": "2", "account": {"id": "other_id", "username": "other", "acct": "other"}, "content": "dele"}

        self.assertTrue(m.item(own_st)["is_own"])
        self.assertFalse(m.item(other_st)["is_own"])

        m.act("delete", {"id": "1"})
        self.assertEqual(calls[-1], ("DELETE", "/api/v1/statuses/1"))

        # Bluesky
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"

        bsky_calls = []
        b.call = lambda mth, nsid, data=None, p=None: bsky_calls.append((mth, nsid, data)) or {}

        own_p = {
            "uri": "at://did:plc:me/app.bsky.feed.post/my_post_key",
            "cid": "cid1",
            "author": {"did": "did:plc:me", "handle": "me.bsky.social"},
            "record": {"text": "meu", "createdAt": "2026-01-01T00:00:00Z"}
        }
        other_p = {
            "uri": "at://did:plc:other/app.bsky.feed.post/other_post_key",
            "cid": "cid2",
            "author": {"did": "did:plc:other", "handle": "other.bsky.social"},
            "record": {"text": "dele", "createdAt": "2026-01-01T00:00:00Z"}
        }

        self.assertTrue(b.item(own_p)["is_own"])
        self.assertFalse(b.item(other_p)["is_own"])

        b.act("delete", {"uri": "at://did:plc:me/app.bsky.feed.post/my_post_key"})
        self.assertEqual(bsky_calls[-1][1], "com.atproto.repo.deleteRecord")
        self.assertEqual(bsky_calls[-1][2]["collection"], "app.bsky.feed.post")
        self.assertEqual(bsky_calls[-1][2]["rkey"], "my_post_key")


class PaginationTests(unittest.TestCase):
    def test_bsky_timeline_cursor(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.jwt = "jwt"
        calls = []
        def fake_call(m, n, d=None, params=None):
            calls.append(params)
            return {"feed": [], "cursor": "next_b_cursor"}

        b.call = fake_call
        items, nxt = b.timeline(cursor="c1")
        self.assertEqual(calls[0]["cursor"], "c1")
        self.assertEqual(nxt, "next_b_cursor")

    def test_masto_timeline_cursor(self):
        m = app.Masto({"instance": "https://m.pt", "token": "tok"})
        calls = []
        def fake_call(mth, pth, data=None, params=None):
            calls.append(params)
            return [{"id": "999", "account": {"id": "1", "username": "u", "acct": "u"}, "content": "x"}]

        m.call = fake_call
        items, nxt = m.timeline(cursor="m1")
        self.assertEqual(calls[0]["max_id"], "m1")
        self.assertEqual(nxt, "999")

    def test_get_timeline_with_cursors(self):
        import io
        from unittest import mock
        bsky_mock = mock.Mock()
        bsky_mock.name = "bluesky"
        bsky_mock.timeline.return_value = ([{"time": "2026-01-01T00:00:00Z", "network": "bluesky"}], "b_next")

        masto_mock = mock.Mock()
        masto_mock.name = "mastodon"
        masto_mock.timeline.return_value = ([{"time": "2026-01-02T00:00:00Z", "network": "mastodon"}], "m_next")

        with mock.patch.dict(app.CLIENTS, {"bluesky": bsky_mock, "mastodon": masto_mock}, clear=True):
            h = object.__new__(app.H)
            h.path = "/api/timeline?cursor_bluesky=b_cur&cursor_mastodon=m_cur"
            h.headers = {"Host": "127.0.0.1:%d" % app.PORT}
            h.wfile = io.BytesIO()
            h.sent = []
            h.send_response = lambda code: h.sent.append(("code", code))
            h.send_header = lambda k, v: h.sent.append((k, v))
            h.end_headers = lambda: None
            h.do_GET()

            code = [v for k, v in h.sent if k == "code"][0]
            self.assertEqual(code, 200)
            res = json.loads(h.wfile.getvalue().decode())
            self.assertEqual(res["cursors"], {"bluesky": "b_next", "mastodon": "m_next"})
            bsky_mock.timeline.assert_called_with(cursor="b_cur")
            masto_mock.timeline.assert_called_with(cursor="m_cur")


class CustomEmojiTests(unittest.TestCase):
    def test_render_custom_emojis_valid(self):
        emojis = [{
            "shortcode": "blobcat",
            "static_url": "https://cdn.masto/blobcat.png",
            "url": "https://cdn.masto/blobcat.gif"
        }]
        html_in = "Olá :blobcat: fixolas!"
        html_out = app.render_custom_emojis(html_in, emojis)
        self.assertIn('<img class="emoji" src="https://cdn.masto/blobcat.png" alt=":blobcat:" title=":blobcat:">', html_out)

    def test_render_custom_emojis_invalid_url(self):
        emojis = [{
            "shortcode": "bad",
            "static_url": "javascript:alert(1)"
        }]
        html_in = "Teste :bad: aqui"
        html_out = app.render_custom_emojis(html_in, emojis)
        self.assertEqual(html_out, html_in)
        self.assertNotIn("<img", html_out)

    def test_masto_item_custom_emojis(self):
        m = app.Masto({"instance": "https://m.pt", "token": "tok"})
        st = {
            "id": "1",
            "account": {
                "id": "1", "username": "alice", "acct": "alice",
                "display_name": "Alice :verified:",
                "emojis": [{"shortcode": "verified", "static_url": "https://m.pt/badge.png"}]
            },
            "content": "<p>Gatinho :blobcat: giro</p>",
            "emojis": [{"shortcode": "blobcat", "static_url": "https://m.pt/cat.png"}],
            "created_at": "2026-01-01T00:00:00Z"
        }
        item = m.item(st)
        self.assertEqual(item["name"], "Alice :verified:")
        self.assertIn('<img class="emoji" src="https://m.pt/badge.png"', item["name_html"])
        self.assertIn('<img class="emoji" src="https://m.pt/cat.png"', item["html"])


class BrandServingTests(unittest.TestCase):
    def _make_handler(self, path):
        h = object.__new__(app.H)
        h.path = path
        h.headers = {"Host": f"127.0.0.1:{app.PORT}"}
        h.wfile = io.BytesIO()
        h.sent = []
        h.send_response = lambda code: h.sent.append(("code", code))
        h.send_header = lambda k, v: h.sent.append((k, v))
        h.end_headers = lambda: None
        return h

    def test_serve_favicon(self):
        h = self._make_handler("/favicon.svg")
        h.do_GET()
        code = [v for k, v in h.sent if k == "code"][0]
        ct = [v for k, v in h.sent if k == "Content-Type"][0]
        self.assertEqual(code, 200)
        self.assertIn("image/svg+xml", ct)

    def test_serve_brand_asset(self):
        h = self._make_handler("/brand/tokens.css")
        h.do_GET()
        code = [v for k, v in h.sent if k == "code"][0]
        ct = [v for k, v in h.sent if k == "Content-Type"][0]
        self.assertEqual(code, 200)
        self.assertIn("text/css", ct)

    def test_brand_path_traversal_blocked(self):
        h = self._make_handler("/brand/../config.example.json")
        h.do_GET()
        code = [v for k, v in h.sent if k == "code"][0]
        self.assertEqual(code, 404)


class HelperRefactorTests(unittest.TestCase):
    def test_strip_re_prefix(self):
        html_input = 'RE: <a href="https://masto.pt/@someone">someone</a> Olá mundo'
        self.assertEqual(app.strip_re_prefix(html_input), "Olá mundo")

        html_suffix = 'Olá mundo <br> RE: <a href="https://masto.pt/@someone">someone</a>'
        self.assertEqual(app.strip_re_prefix(html_suffix), "Olá mundo")

        # None or empty
        self.assertIsNone(app.strip_re_prefix(None))
        self.assertEqual(app.strip_re_prefix(""), "")

    def test_extract_masto_media(self):
        st = {
            "media_attachments": [
                {"type": "image", "url": "https://img.pt/1.jpg", "preview_url": "https://img.pt/1_thumb.jpg", "description": "Alt 1"}
            ],
            "card": {"url": "https://card.pt", "image": "https://card.pt/thumb.jpg", "title": "Card Title"}
        }
        media = app.extract_masto_media(st)
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]["type"], "image")

        # Fallback to card when no media attachments
        st_no_media = {
            "media_attachments": [],
            "card": {"url": "https://card.pt", "image": "https://card.pt/thumb.jpg", "title": "Card Title", "description": "Card Desc"}
        }
        card_media = app.extract_masto_media(st_no_media, allow_card=True)
        self.assertEqual(len(card_media), 1)
        self.assertEqual(card_media[0]["type"], "external")
        self.assertEqual(card_media[0]["url"], "https://card.pt")

        card_media_disallowed = app.extract_masto_media(st_no_media, allow_card=False)
        self.assertEqual(len(card_media_disallowed), 0)


class CliAndMiscTests(unittest.TestCase):
    def test_user_agent(self):
        with mock.patch("urllib.request.urlopen") as mock_open:
            mock_resp = mock.MagicMock()
            mock_resp.read.return_value = b"{}"
            mock_resp.headers = {}
            mock_open.return_value.__enter__.return_value = mock_resp
            app.http("GET", "https://example.com/api")
            req = mock_open.call_args[0][0]
            self.assertEqual(req.get_header("User-agent"), "MastoSky/1.0")

    def test_verbose_logging_enabled(self):
        h = object.__new__(app.H)
        h.verbose = True
        with mock.patch.object(app.BaseHTTPRequestHandler, "log_message") as mock_log:
            h.log_message("test format %s", "arg")
            mock_log.assert_called_once_with("test format %s", "arg")

    def test_verbose_logging_disabled(self):
        h = object.__new__(app.H)
        h.verbose = False
        with mock.patch.object(app.BaseHTTPRequestHandler, "log_message") as mock_log:
            h.log_message("test format %s", "arg")
            mock_log.assert_not_called()


class ProfileTests(unittest.TestCase):
    def test_bsky_profile(self):
        b = app.Bsky({"handle": "alice.bsky.social", "app_password": "pass"})
        b.did = "did:plc:alice"
        b.jwt = "jwt"
        with mock.patch.object(b, "call") as mock_call:
            mock_call.return_value = {
                "displayName": "Alice Wonderland",
                "handle": "alice.bsky.social",
                "avatar": "https://cdn.bsky/avatar.jpg",
                "banner": "https://cdn.bsky/banner.jpg",
                "description": "Hello world\nhttps://example.com",
                "followersCount": 42,
                "followsCount": 10,
                "postsCount": 99
            }
            prof = b.profile()
            self.assertEqual(prof["network"], "bluesky")
            self.assertEqual(prof["name"], "Alice Wonderland")
            self.assertEqual(prof["handle"], "@alice.bsky.social")
            self.assertEqual(prof["followers"], 42)
            self.assertEqual(prof["posts_count"], 99)
            self.assertIn("<br>", prof["bio"])
            self.assertIn('href="https://example.com"', prof["bio"])

    def test_masto_profile(self):
        m = app.Masto({"instance": "https://masto.pt", "token": "tok"})
        with mock.patch.object(m, "call") as mock_call:
            mock_call.return_value = {
                "id": "1234",
                "username": "bob",
                "acct": "bob",
                "display_name": "Bob :verified:",
                "avatar": "https://masto.pt/av.jpg",
                "header": "https://masto.pt/head.jpg",
                "note": "<p>Olá do Mastodon :blobcat:</p>",
                "followers_count": 100,
                "following_count": 50,
                "statuses_count": 250,
                "url": "https://masto.pt/@bob",
                "emojis": [
                    {"shortcode": "verified", "static_url": "https://masto.pt/ver.png"},
                    {"shortcode": "blobcat", "static_url": "https://masto.pt/cat.png"}
                ]
            }
            prof = m.profile()
            self.assertEqual(prof["network"], "mastodon")
            self.assertEqual(prof["name"], "Bob :verified:")
            self.assertIn('<img class="emoji" src="https://masto.pt/ver.png"', prof["name_html"])
            self.assertIn('<img class="emoji" src="https://masto.pt/cat.png"', prof["bio"])
            self.assertEqual(prof["followers"], 100)
            self.assertEqual(prof["posts_count"], 250)

    def test_profile_endpoints(self):
        bsky_mock = mock.MagicMock()
        bsky_mock.name = "bluesky"
        bsky_mock.profile.return_value = {"network": "bluesky", "name": "Alice"}
        bsky_mock.author_feed.return_value = ([{"time": "2026-01-01T00:00:00Z", "network": "bluesky"}], "b_cur")

        masto_mock = mock.MagicMock()
        masto_mock.name = "mastodon"
        masto_mock.profile.return_value = {"network": "mastodon", "name": "Bob"}
        masto_mock.author_feed.return_value = ([{"time": "2026-01-02T00:00:00Z", "network": "mastodon"}], "m_cur")

        with mock.patch.dict(app.CLIENTS, {"bluesky": bsky_mock, "mastodon": masto_mock}, clear=True):
            # Test /api/profile
            h = object.__new__(app.H)
            h.path = "/api/profile"
            h.headers = {"Host": f"127.0.0.1:{app.PORT}"}
            h.wfile = io.BytesIO()
            h.sent = []
            h.send_response = lambda code: h.sent.append(("code", code))
            h.send_header = lambda k, v: h.sent.append((k, v))
            h.end_headers = lambda: None
            h.do_GET()

            code = [v for k, v in h.sent if k == "code"][0]
            self.assertEqual(code, 200)
            res = json.loads(h.wfile.getvalue().decode())
            self.assertEqual(res["profiles"]["bluesky"]["name"], "Alice")
            self.assertEqual(res["profiles"]["mastodon"]["name"], "Bob")

            # Test /api/profile/feed
            h2 = object.__new__(app.H)
            h2.path = "/api/profile/feed"
            h2.headers = {"Host": f"127.0.0.1:{app.PORT}"}
            h2.wfile = io.BytesIO()
            h2.sent = []
            h2.send_response = lambda code: h2.sent.append(("code", code))
            h2.send_header = lambda k, v: h2.sent.append((k, v))
            h2.end_headers = lambda: None
            h2.do_GET()

            code2 = [v for k, v in h2.sent if k == "code"][0]
            self.assertEqual(code2, 200)
            res2 = json.loads(h2.wfile.getvalue().decode())
            self.assertEqual(len(res2["items"]), 2)
            self.assertEqual(res2["cursors"], {"bluesky": "b_cur", "mastodon": "m_cur"})


if __name__ == "__main__":
    unittest.main()
