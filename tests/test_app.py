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
        self.assertEqual(q["ref"]["uri"], "at://did:plc:x/app.bsky.feed.post/abc")
        self.assertEqual(q["author_handle"], "a.bsky.social")

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
        q = app.parse_masto_quote({"quote": {"state": "accepted", "quoted_status": self._status(id="789")}})
        self.assertEqual(q["handle"], "@m@x.pt")
        self.assertEqual(q["html"], "citado")
        self.assertEqual(q["ref"], {"id": "789"})

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
        self.assertEqual(it["text"], "x")

    def test_masto_item_text(self):
        st = {"id": "1", "account": {"username": "u", "acct": "u@inst"},
              "content": "<p>Olá mundo <b>fediverso</b></p>",
              "spoiler_text": "Aviso",
              "created_at": "2026-01-01T00:00:00Z"}
        it = app.Masto({"instance": "https://x", "token": "t"}).item(st)
        self.assertIn("Olá mundo fediverso", it["text"])
        self.assertIn("[Aviso]", it["text"])


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

    def test_index_serves_session_token(self):
        h = self._handler("127.0.0.1:%d" % app.PORT)
        h.path = "/"
        h.do_GET()
        body = h.wfile.getvalue().decode("utf-8")
        self.assertIn(f'<meta name="csrf-token" content="{app.SESSION_TOKEN}">', body)

    def test_csrf_endpoint(self):
        h = self._handler("127.0.0.1:%d" % app.PORT)
        h.path = "/api/csrf"
        h.do_GET()
        body = json.loads(h.wfile.getvalue())
        self.assertEqual(body.get("token"), app.SESSION_TOKEN)

    def test_options_allowed(self):
        h = self._handler("127.0.0.1:%d" % app.PORT, "http://127.0.0.1:%d" % app.PORT)
        h.do_OPTIONS()
        code = [v for k, v in h.sent if k == "code"][0]
        self.assertEqual(code, 204)

    def test_options_rejected_for_foreign_origin(self):
        h = self._handler("127.0.0.1:%d" % app.PORT, "https://evil.example")
        h.do_OPTIONS()
        code = [v for k, v in h.sent if k == "code"][0]
        self.assertEqual(code, 403)


class PostHandlerTests(unittest.TestCase):
    def _post(self, path, body, length=None, token=None):
        import io
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        h = object.__new__(app.H)
        h.path = path
        tok = app.SESSION_TOKEN if token is None else token
        h.headers = {"Host": "127.0.0.1:%d" % app.PORT,
                     "Content-Length": str(len(raw)) if length is None else length}
        if tok:
            h.headers["X-CSRF-Token"] = tok
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

    def test_csrf_token_required(self):
        code, r = self._post("/api/post", b"{}", token="")
        self.assertEqual(code, 403)
        self.assertIn("Token de sessão", r["error"])

    def test_csrf_token_invalid_rejected(self):
        code, r = self._post("/api/post", b"{}", token="token-falso-123")
        self.assertEqual(code, 403)
        self.assertIn("Token de sessão", r["error"])

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

    def test_partial_success_post(self):
        from unittest import mock
        masto_client = mock.Mock()
        masto_client.post.side_effect = RuntimeError("Mastodon timeout")
        with mock.patch.dict(app.CLIENTS, {"bluesky": self.client, "mastodon": masto_client}):
            code, r = self._post("/api/post", {"text": "Olá", "targets": ["bluesky", "mastodon"]})
            self.assertEqual(code, 200)
            self.assertEqual(r["bluesky"], "ok")
            self.assertEqual(r["mastodon"], "Mastodon timeout")

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

    def test_thread_validation(self):
        # Empty thread
        self.assertEqual(self._post("/api/post", {"thread": [], "targets": ["bluesky"]})[0], 400)
        # Not a list
        self.assertEqual(self._post("/api/post", {"thread": "invalid", "targets": ["bluesky"]})[0], 400)
        # Thread too long
        self.assertEqual(self._post("/api/post", {"thread": [{"text": str(i)} for i in range(26)], "targets": ["bluesky"]})[0], 400)
        # Thread post with empty content
        self.assertEqual(self._post("/api/post", {"thread": [{"text": "ok"}, {"text": ""}], "targets": ["bluesky"]})[0], 400)

    def test_thread_publishing_chain_bsky(self):
        self.client.post.side_effect = [
            {"uri": "at://did:plc:123/app.bsky.feed.post/1", "cid": "cid1"},
            {"uri": "at://did:plc:123/app.bsky.feed.post/2", "cid": "cid2"},
            {"uri": "at://did:plc:123/app.bsky.feed.post/3", "cid": "cid3"}
        ]
        payload = {
            "targets": ["bluesky"],
            "thread": [
                {"text": "Primeiro post do fio"},
                {"text": "Segundo post do fio"},
                {"text": "Terceiro post do fio"}
            ]
        }
        code, r = self._post("/api/post", payload)
        self.assertEqual(code, 200)
        self.assertEqual(r, {"bluesky": "ok"})
        self.assertEqual(self.client.post.call_count, 3)

        # Call 1: root post
        args1, kwargs1 = self.client.post.call_args_list[0]
        self.assertEqual(args1[0], "Primeiro post do fio")
        self.assertIsNone(args1[1])

        # Call 2: replies to post 1
        args2, kwargs2 = self.client.post.call_args_list[1]
        self.assertEqual(args2[0], "Segundo post do fio")
        self.assertEqual(args2[1]["root"], {"uri": "at://did:plc:123/app.bsky.feed.post/1", "cid": "cid1"})
        self.assertEqual(args2[1]["uri"], "at://did:plc:123/app.bsky.feed.post/1")
        self.assertEqual(args2[1]["cid"], "cid1")

        # Call 3: root is post 1, parent is post 2
        args3, kwargs3 = self.client.post.call_args_list[2]
        self.assertEqual(args3[0], "Terceiro post do fio")
        self.assertEqual(args3[1]["root"], {"uri": "at://did:plc:123/app.bsky.feed.post/1", "cid": "cid1"})
        self.assertEqual(args3[1]["uri"], "at://did:plc:123/app.bsky.feed.post/2")
        self.assertEqual(args3[1]["cid"], "cid2")

    def test_thread_publishing_chain_mastodon(self):
        from unittest import mock
        masto_client = mock.Mock()
        masto_client.post.side_effect = [
            {"id": "1001"},
            {"id": "1002"},
            {"id": "1003"}
        ]
        with mock.patch.dict(app.CLIENTS, {"mastodon": masto_client}):
            payload = {
                "targets": ["mastodon"],
                "thread": [
                    {"text": "Masto 1"},
                    {"text": "Masto 2"},
                    {"text": "Masto 3"}
                ]
            }
            code, r = self._post("/api/post", payload)
            self.assertEqual(code, 200)
            self.assertEqual(r, {"mastodon": "ok"})
            self.assertEqual(masto_client.post.call_count, 3)

            # Call 1: root
            self.assertIsNone(masto_client.post.call_args_list[0][0][1])

            # Call 2: in_reply_to 1001
            self.assertEqual(masto_client.post.call_args_list[1][0][1], {"id": "1001"})

            # Call 3: in_reply_to 1002
            self.assertEqual(masto_client.post.call_args_list[2][0][1], {"id": "1002"})

    def test_reply_post_endpoint(self):
        from unittest import mock
        masto_client = mock.Mock()
        masto_client.post.return_value = {"id": "9999"}
        with mock.patch.dict(app.CLIENTS, {"mastodon": masto_client}):
            payload = {
                "text": "@user olá resposta",
                "reply": {
                    "network": "mastodon",
                    "ref": {"id": "12345"}
                }
            }
            code, r = self._post("/api/post", payload)
            self.assertEqual(code, 200)
            self.assertEqual(r, {"mastodon": "ok"})
            self.assertEqual(masto_client.post.call_count, 1)
            # Verifica se foi chamado com in_reply_to_id correto
            args, kwargs = masto_client.post.call_args
            self.assertEqual(args[0], "@user olá resposta")
            self.assertEqual(args[1], {"id": "12345"})

    def test_follow_endpoint_validation_and_actions(self):
        # Missing network
        code, r = self._post("/api/follow", {"action": "follow", "actor": "alice"})
        self.assertEqual(code, 400)
        self.assertIn("Rede inválida", r["error"])

        # Invalid action
        code, r = self._post("/api/follow", {"network": "bluesky", "action": "fly", "actor": "alice"})
        self.assertEqual(code, 400)
        self.assertIn("Ação inválida", r["error"])

        # Missing actor
        code, r = self._post("/api/follow", {"network": "bluesky", "action": "follow"})
        self.assertEqual(code, 400)
        self.assertIn("Identificador", r["error"])

        # Successful follow
        self.client.follow.return_value = {"uri": "at://did:plc:me/app.bsky.graph.follow/3k1"}
        code, r = self._post("/api/follow", {"network": "bluesky", "action": "follow", "actor": "alice"})
        self.assertEqual(code, 200)
        self.assertTrue(r["ok"])
        self.assertTrue(r["following"])
        self.assertEqual(r["follow_uri"], "at://did:plc:me/app.bsky.graph.follow/3k1")
        self.client.follow.assert_called_with("alice")

        # Successful unfollow
        self.client.unfollow.return_value = {}
        code, r = self._post("/api/follow", {"network": "bluesky", "action": "unfollow", "actor": "alice", "follow_uri": "at://did:plc:me/app.bsky.graph.follow/3k1"})
        self.assertEqual(code, 200)
        self.assertTrue(r["ok"])
        self.assertFalse(r["following"])
        self.client.unfollow.assert_called_with("alice", follow_uri="at://did:plc:me/app.bsky.graph.follow/3k1")

        # CSRF failure
        code, r = self._post("/api/follow", {"network": "bluesky", "action": "follow", "actor": "alice"}, token="BAD_TOKEN")
        self.assertEqual(code, 403)


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

    def test_bsky_notification_subject_fallback_and_preview(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"

        def mock_call(m, nsid, d=None, params=None):
            if nsid == "app.bsky.notification.listNotifications":
                return {
                    "notifications": [
                        {
                            "uri": "at://did:plc:user1/app.bsky.feed.like/1",
                            "cid": "cid1",
                            "author": {"handle": "user1.bsky.social", "displayName": "User One"},
                            "reason": "like",
                            # reasonSubject omitido deliberadamente
                            "record": {
                                "$type": "app.bsky.feed.like",
                                "subject": {"uri": "at://did:plc:me/app.bsky.feed.post/post1"}
                            },
                            "indexedAt": "2026-01-01T00:00:00Z"
                        }
                    ],
                    "cursor": "c1"
                }
            elif nsid == "app.bsky.feed.getPosts":
                return {
                    "posts": [
                        {
                            "uri": "at://did:plc:me/app.bsky.feed.post/post1",
                            "author": {"handle": "me.bsky.social"},
                            "record": {"text": "Texto do meu post original"}
                        }
                    ]
                }
            return {}

        b.call = mock_call
        notifs, cursor = b.notifications()
        self.assertEqual(len(notifs), 1)
        self.assertEqual(cursor, "c1")
        self.assertIn("Texto do meu post original", notifs[0]["html"])

    def test_bsky_notification_like_on_repost_resolution(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"

        get_posts_called_with = []

        def mock_call(m, nsid, d=None, params=None):
            if nsid == "app.bsky.notification.listNotifications":
                return {
                    "notifications": [
                        {
                            "uri": "at://did:plc:andre/app.bsky.feed.like/like1",
                            "cid": "cid1",
                            "author": {"handle": "andre-wemans.bsky.social", "displayName": "André Wemans"},
                            "reason": "like",
                            # Em likes de reposts, reasonSubject aponta para o feed.repost do utilizador:
                            "reasonSubject": "at://did:plc:me/app.bsky.feed.repost/repost1",
                            # E record.subject.uri aponta para o post original:
                            "record": {
                                "$type": "app.bsky.feed.like",
                                "subject": {"uri": "at://did:plc:jocandi/app.bsky.feed.post/3mzaiad2oz422"}
                            },
                            "indexedAt": "2026-01-01T00:00:00Z"
                        }
                    ],
                    "cursor": "c2"
                }
            elif nsid == "app.bsky.feed.getPosts":
                get_posts_called_with.extend([v for k, v in (params or []) if k == "uris"])
                return {
                    "posts": [
                        {
                            "uri": "at://did:plc:jocandi/app.bsky.feed.post/3mzaiad2oz422",
                            "author": {"handle": "jocandi.bsky.social"},
                            "record": {"text": "Eu votei neste homem para que o Fascismo não regressasse!"}
                        }
                    ]
                }
            return {}

        b.call = mock_call
        notifs, cursor = b.notifications()
        self.assertEqual(len(notifs), 1)
        self.assertEqual(cursor, "c2")
        self.assertEqual(notifs[0]["kind"], "like_repost")
        # Garante que getPosts foi chamado com o URI do post original e NÃO com o URI do repost:
        self.assertIn("at://did:plc:jocandi/app.bsky.feed.post/3mzaiad2oz422", get_posts_called_with)
        self.assertNotIn("at://did:plc:me/app.bsky.feed.repost/repost1", get_posts_called_with)
        # Garante o texto do preview e que o link aponta para o autor do post (jocandi) e não para o liker (andre):
        self.assertIn("Eu votei neste homem", notifs[0]["html"])
        self.assertEqual(notifs[0]["url"], "https://bsky.app/profile/jocandi.bsky.social/post/3mzaiad2oz422")
        self.assertIsNotNone(notifs[0]["target_post"])
        self.assertEqual(notifs[0]["target_post"]["author_handle"], "@jocandi.bsky.social")

    def test_bsky_notification_with_image_and_external_embed(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"

        def mock_call(m, nsid, d=None, params=None):
            if nsid == "app.bsky.notification.listNotifications":
                return {
                    "notifications": [
                        {
                            "uri": "at://did:plc:user1/app.bsky.feed.like/1",
                            "cid": "cid1",
                            "author": {"handle": "user1.bsky.social", "displayName": "User One"},
                            "reason": "like",
                            "record": {
                                "$type": "app.bsky.feed.like",
                                "subject": {"uri": "at://did:plc:me/app.bsky.feed.post/imgpost"}
                            },
                            "indexedAt": "2026-01-01T00:00:00Z"
                        },
                        {
                            "uri": "at://did:plc:user2/app.bsky.feed.post/reply1",
                            "cid": "cid2",
                            "author": {"handle": "user2.bsky.social", "displayName": "User Two"},
                            "reason": "reply",
                            "record": {
                                "$type": "app.bsky.feed.post",
                                "text": "Olha este link",
                                "reply": {"root": {"uri": "at://did:plc:me/app.bsky.feed.post/myroot", "cid": "croot"}},
                                "embed": {
                                    "$type": "app.bsky.embed.external#view",
                                    "external": {
                                        "uri": "https://example.com/article",
                                        "title": "Exemplo",
                                        "description": "Descricao",
                                        "thumb": "https://cdn.example.com/thumb.jpg"
                                    }
                                }
                            },
                            "indexedAt": "2026-01-01T01:00:00Z"
                        }
                    ],
                    "cursor": "c3"
                }
            elif nsid == "app.bsky.feed.getPosts":
                return {
                    "posts": [
                        {
                            "uri": "at://did:plc:me/app.bsky.feed.post/imgpost",
                            "author": {"handle": "me.bsky.social"},
                            "record": {"text": ""},
                            "embed": {
                                "$type": "app.bsky.embed.images#view",
                                "images": [
                                    {"fullsize": "https://cdn.bsky.app/img/full.jpg", "thumb": "https://cdn.bsky.app/img/thumb.jpg", "alt": "Foto bonita"}
                                ]
                            }
                        }
                    ]
                }
            return {}

        b.call = mock_call
        notifs, _ = b.notifications()
        self.assertEqual(len(notifs), 2)
        # Notificação 1 (like num post com imagem sem texto):
        self.assertEqual(len(notifs[0]["media"]), 1)
        self.assertEqual(notifs[0]["media"][0]["type"], "image")
        self.assertEqual(notifs[0]["media"][0]["url"], "https://cdn.bsky.app/img/full.jpg")
        self.assertNotIn("📷 [Imagem]", notifs[0]["html"])  # Media visual fornecida diretamente

        # Notificação 2 (reply com embed externo):
        self.assertEqual(len(notifs[1]["media"]), 1)
        self.assertEqual(notifs[1]["media"][0]["type"], "external")
        self.assertEqual(notifs[1]["media"][0]["url"], "https://example.com/article")
        self.assertEqual(notifs[1]["media"][0]["title"], "Exemplo")

    def test_bsky_notification_with_raw_blob_images(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"

        def mock_call(m, nsid, d=None, params=None):
            if nsid == "app.bsky.notification.listNotifications":
                return {
                    "notifications": [
                        {
                            "uri": "at://did:plc:ocaodanado/app.bsky.feed.like/like99",
                            "cid": "cid99",
                            "author": {"handle": "ocaodanado.bsky.social", "displayName": "O Cão Danado"},
                            "reason": "like",
                            "record": {
                                "$type": "app.bsky.feed.like",
                                "subject": {"uri": "at://did:plc:me/app.bsky.feed.post/post_blob"}
                            },
                            "indexedAt": "2026-01-01T02:00:00Z"
                        }
                    ]
                }
            elif nsid == "app.bsky.feed.getPosts":
                return {
                    "posts": [
                        {
                            "uri": "at://did:plc:me/app.bsky.feed.post/post_blob",
                            "author": {"handle": "me.bsky.social", "did": "did:plc:me"},
                            "record": {
                                "text": "",
                                "embed": {
                                    "$type": "app.bsky.embed.images",
                                    "images": [
                                        {
                                            "alt": "Foto de cao",
                                            "image": {
                                                "$type": "blob",
                                                "ref": {"$link": "bafkreia123456789"},
                                                "mimeType": "image/jpeg"
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                }
            return {}

        b.call = mock_call
        notifs, _ = b.notifications()
        self.assertEqual(len(notifs), 1)
        self.assertEqual(len(notifs[0]["media"]), 1)
        self.assertEqual(notifs[0]["media"][0]["type"], "image")
        self.assertIn("bafkreia123456789", notifs[0]["media"][0]["url"])
        self.assertIn("did:plc:me", notifs[0]["media"][0]["url"])
        # Garante que não é exibido o texto "📷 [Imagem]" quando a media foi extraída com sucesso:
        self.assertEqual(notifs[0]["html"], "")

    def test_bsky_item_no_duplicate_media(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        # Post que contém tanto a view hidratada como o embed bruto no registo:
        p = {
            "uri": "at://did:plc:me/app.bsky.feed.post/123",
            "cid": "cid123",
            "author": {"handle": "me.bsky.social", "did": "did:plc:me"},
            "record": {
                "text": "Post com fotos",
                "createdAt": "2026-01-01T00:00:00Z",
                "embed": {
                    "$type": "app.bsky.embed.images",
                    "images": [
                        {"image": {"ref": {"$link": "bafk1"}}, "alt": "Foto 1"},
                        {"image": {"ref": {"$link": "bafk2"}}, "alt": "Foto 2"}
                    ]
                }
            },
            "embed": {
                "$type": "app.bsky.embed.images#view",
                "images": [
                    {"thumb": "https://cdn.bsky.app/img/feed_thumbnail/plain/did:plc:me/bafk1@jpeg", "fullsize": "https://cdn.bsky.app/img/feed_fullsize/plain/did:plc:me/bafk1@jpeg", "alt": "Foto 1"},
                    {"thumb": "https://cdn.bsky.app/img/feed_thumbnail/plain/did:plc:me/bafk2@jpeg", "fullsize": "https://cdn.bsky.app/img/feed_fullsize/plain/did:plc:me/bafk2@jpeg", "alt": "Foto 2"}
                ]
            }
        }
        item = b.item(p)
        # Deve ter exatamente 2 imagens, sem duplicar para 4:
        self.assertEqual(len(item["media"]), 2)

    def test_masto_notification_with_media_and_card(self):
        m = app.Masto({"instance": "https://mastodon.social", "token": "tok"})
        raw_notifs = [
            {
                "id": "1001",
                "type": "favourite",
                "created_at": "2026-01-01T12:00:00Z",
                "account": {"id": 1, "username": "alice", "acct": "alice@mastodon.social", "display_name": "Alice"},
                "status": {
                    "id": "999",
                    "content": "<p>Vejam isto com link e anexo</p>",
                    "url": "https://mastodon.social/@alice/999",
                    "media_attachments": [
                        {"type": "image", "url": "https://files.mastodon.social/media1.png", "preview_url": "https://files.mastodon.social/media1_thumb.png", "description": "Screenshot"}
                    ]
                }
            },
            {
                "id": "1002",
                "type": "favourite",
                "created_at": "2026-01-01T13:00:00Z",
                "account": {"id": 2, "username": "bob", "acct": "bob@mastodon.social", "display_name": "Bob"},
                "status": {
                    "id": "998",
                    "content": "<p>Link externo</p>",
                    "url": "https://mastodon.social/@bob/998",
                    "card": {
                        "url": "https://news.ycombinator.com",
                        "title": "Hacker News",
                        "description": "Tech news",
                        "image": "https://files.mastodon.social/hn.png"
                    }
                }
            }
        ]
        m.call = lambda method, path, params=None: raw_notifs
        notifs, cursor = m.notifications()
        self.assertEqual(len(notifs), 2)
        self.assertEqual(cursor, "1002")
        # Item 1: tem imagem
        self.assertEqual(len(notifs[0]["media"]), 1)
        self.assertEqual(notifs[0]["media"][0]["type"], "image")
        self.assertEqual(notifs[0]["media"][0]["url"], "https://files.mastodon.social/media1.png")
        # Item 2: tem card externo
        self.assertEqual(len(notifs[1]["media"]), 1)
        self.assertEqual(notifs[1]["media"][0]["type"], "external")
        self.assertEqual(notifs[1]["media"][0]["url"], "https://news.ycombinator.com")
        self.assertEqual(notifs[1]["media"][0]["title"], "Hacker News")



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
        m.follow("100")
        m.unfollow("100")

        self.assertEqual(calls, [
            ("POST", "/api/v1/statuses/100/favourite"),
            ("POST", "/api/v1/statuses/100/unfavourite"),
            ("POST", "/api/v1/statuses/100/reblog"),
            ("POST", "/api/v1/statuses/100/unreblog"),
            ("POST", "/api/v1/accounts/100/follow"),
            ("POST", "/api/v1/accounts/100/unfollow")
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

        b.follow("did:plc:target")
        self.assertEqual(calls[-1][1], "com.atproto.repo.createRecord")
        self.assertEqual(calls[-1][2]["collection"], "app.bsky.graph.follow")
        self.assertEqual(calls[-1][2]["record"]["subject"], "did:plc:target")

        b.unfollow("target", follow_uri="at://did:plc:me/app.bsky.graph.follow/fol123")
        self.assertEqual(calls[-1][1], "com.atproto.repo.deleteRecord")
        self.assertEqual(calls[-1][2]["collection"], "app.bsky.graph.follow")
        self.assertEqual(calls[-1][2]["rkey"], "fol123")

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

    def test_user_profile_and_feed_endpoints(self):
        bsky_mock = mock.MagicMock()
        bsky_mock.name = "bluesky"
        bsky_mock.user_profile.return_value = {"network": "bluesky", "name": "Charlie", "handle": "@charlie.bsky.social"}
        bsky_mock.user_feed.return_value = ([{"time": "2026-01-03T00:00:00Z", "network": "bluesky"}], "c_cur")

        with mock.patch.dict(app.CLIENTS, {"bluesky": bsky_mock}, clear=True):
            # Test /api/user_profile
            h = object.__new__(app.H)
            h.path = "/api/user_profile?network=bluesky&actor=charlie.bsky.social"
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
            self.assertEqual(res["profile"]["name"], "Charlie")
            bsky_mock.user_profile.assert_called_with("charlie.bsky.social")

            # Test /api/user_feed
            h2 = object.__new__(app.H)
            h2.path = "/api/user_feed?network=bluesky&actor=charlie.bsky.social&cursor=prev"
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
            self.assertEqual(len(res2["items"]), 1)
            self.assertEqual(res2["cursor"], "c_cur")
            bsky_mock.user_feed.assert_called_with("charlie.bsky.social", cursor="prev")

    def test_search_endpoints(self):
        bsky_mock = mock.MagicMock()
        bsky_mock.name = "bluesky"
        bsky_mock.search.return_value = {
            "posts": [{"time": "2026-01-02T12:00:00Z", "text": "Bluesky post", "network": "bluesky"}],
            "actors": [{"name": "User B", "network": "bluesky"}],
            "hashtags": [{"name": "tech", "network": "bluesky"}]
        }

        masto_mock = mock.MagicMock()
        masto_mock.name = "mastodon"
        masto_mock.search.return_value = {
            "posts": [{"time": "2026-01-03T12:00:00Z", "text": "Mastodon post", "network": "mastodon"}],
            "actors": [{"name": "User M", "network": "mastodon"}],
            "hashtags": [{"name": "tech", "network": "mastodon"}]
        }

        with mock.patch.dict(app.CLIENTS, {"bluesky": bsky_mock, "mastodon": masto_mock}, clear=True):
            # 1. Pesquisa vazia
            h = object.__new__(app.H)
            h.path = "/api/search?q="
            h.headers = {"Host": f"127.0.0.1:{app.PORT}"}
            h.wfile = io.BytesIO()
            h.sent = []
            h.send_response = lambda code: h.sent.append(("code", code))
            h.send_header = lambda k, v: h.sent.append((k, v))
            h.end_headers = lambda: None
            h.do_GET()
            res = json.loads(h.wfile.getvalue().decode())
            self.assertEqual(res["posts"], [])
            self.assertEqual(res["actors"], [])
            self.assertEqual(res["hashtags"], [])

            # 2. Pesquisa unificada com query
            h2 = object.__new__(app.H)
            h2.path = "/api/search?q=tech&type=all"
            h2.headers = {"Host": f"127.0.0.1:{app.PORT}"}
            h2.wfile = io.BytesIO()
            h2.sent = []
            h2.send_response = lambda code: h2.sent.append(("code", code))
            h2.send_header = lambda k, v: h2.sent.append((k, v))
            h2.end_headers = lambda: None
            h2.do_GET()
            res2 = json.loads(h2.wfile.getvalue().decode())
            self.assertEqual(len(res2["posts"]), 2)
            # Ordenado por mais recente (Mastodon 2026-01-03 antes de Bluesky 2026-01-02)
            self.assertEqual(res2["posts"][0]["text"], "Mastodon post")
            self.assertEqual(res2["posts"][1]["text"], "Bluesky post")
            self.assertEqual(len(res2["actors"]), 2)
            self.assertEqual(len(res2["hashtags"]), 2)
            bsky_mock.search.assert_called_with("tech", search_type="all", limit=25)
            masto_mock.search.assert_called_with("tech", search_type="all", limit=25)

            # 3. Pesquisa filtrada por rede
            h3 = object.__new__(app.H)
            h3.path = "/api/search?q=tech&network=bluesky"
            h3.headers = {"Host": f"127.0.0.1:{app.PORT}"}
            h3.wfile = io.BytesIO()
            h3.sent = []
            h3.send_response = lambda code: h3.sent.append(("code", code))
            h3.send_header = lambda k, v: h3.sent.append((k, v))
            h3.end_headers = lambda: None
            h3.do_GET()
            res3 = json.loads(h3.wfile.getvalue().decode())
            self.assertEqual(len(res3["posts"]), 1)
            self.assertEqual(res3["posts"][0]["network"], "bluesky")

    def test_bsky_and_masto_search_helpers(self):
        bsky = app.Bsky({"handle": "test.bsky.social", "password": "pass"})
        bsky.call = mock.MagicMock()
        bsky.call.side_effect = [
            {"posts": [{"uri": "at://1", "cid": "c1", "author": {"handle": "u1"}, "record": {"$type": "app.bsky.feed.post", "text": "Bsky tag", "createdAt": "2026-01-01T00:00:00Z"}}]},
            {"actors": [{"did": "did:1", "handle": "u1", "displayName": "User One", "avatar": "https://img/av.jpg"}]}
        ]
        with mock.patch.object(bsky, "_ensure"):
            res_b = bsky.search("#tag", search_type="all")
            self.assertEqual(len(res_b["posts"]), 1)
            self.assertEqual(len(res_b["actors"]), 1)
            self.assertEqual(len(res_b["hashtags"]), 1)
            self.assertEqual(res_b["hashtags"][0]["name"], "tag")

        masto = app.Masto({"instance": "masto.test", "token": "tok"})
        masto.call = mock.MagicMock(return_value={
            "statuses": [{"id": "s1", "content": "Masto status", "account": {"id": "1", "acct": "m1", "username": "m1"}}],
            "accounts": [{"id": "a1", "acct": "m1", "username": "m1", "display_name": "Masto User"}],
            "hashtags": [{"name": "tag", "url": "https://masto.test/tags/tag"}]
        })
        res_m = masto.search("tag", search_type="all")
        self.assertEqual(len(res_m["posts"]), 1)
        self.assertEqual(len(res_m["actors"]), 1)
        self.assertEqual(len(res_m["hashtags"]), 1)
        self.assertEqual(res_m["hashtags"][0]["name"], "tag")

    def test_bsky_and_masto_user_profile_methods(self):
        b = app.Bsky({"handle": "me.bsky.social", "app_password": "p"})
        b.did = "did:plc:me"
        b.jwt = "jwt"
        b_calls = []
        def mock_b_call(m, n, d=None, params=None):
            b_calls.append((m, n, params))
            return {
                "displayName": "User", "handle": "user.bsky.social", "followersCount": 42,
                "viewer": {"following": "at://did:plc:me/app.bsky.graph.follow/123"}
            }
        b.call = mock_b_call
        prof = b.user_profile("@user.bsky.social")
        self.assertEqual(prof["name"], "User")
        self.assertEqual(prof["followers"], 42)
        self.assertTrue(prof["is_following"])
        self.assertEqual(b_calls[0][2], {"actor": "user.bsky.social"})

        m = app.Masto({"instance": "https://m.pt", "token": "tok"})
        m.my_id = "99999"
        m_calls = []
        def mock_m_call(mth, pth, data=None, params=None, timeout=30):
            m_calls.append((mth, pth, params))
            if pth.startswith("/api/v1/accounts/relationships"):
                return [{"id": "12345", "following": True}]
            return {
                "id": 12345, "username": "bob", "acct": "bob@inst", "display_name": "Bob",
                "statuses_count": 10
            }
        m.call = mock_m_call
        prof_m = m.user_profile("12345")
        self.assertEqual(prof_m["id"], "12345")
        self.assertEqual(prof_m["name"], "Bob")
        self.assertEqual(prof_m["posts_count"], 10)
        self.assertTrue(prof_m["is_following"])
        self.assertEqual(len(m_calls), 2)
        self.assertEqual(m_calls[1][1], "/api/v1/accounts/relationships")
        self.assertEqual(m_calls[1][2], {"id[]": ["12345"]})

    def test_masto_call_doseq_encoding(self):
        m = app.Masto({"instance": "https://m.pt", "token": "tok"})
        with mock.patch("app.http") as mock_http:
            mock_http.return_value = [{"id": "123", "following": True}]
            m.call("GET", "/api/v1/accounts/relationships", params={"id[]": ["123"]})
            mock_http.assert_called_once()
            called_url = mock_http.call_args[0][1]
            self.assertEqual(called_url, "https://m.pt/api/v1/accounts/relationships?id%5B%5D=123")


class ProxyImageTests(unittest.TestCase):
    def test_blocks_localhost_and_private_ips(self):
        for bad in ("http://localhost/pic.jpg", "http://127.0.0.1/pic.jpg", "http://192.168.0.1/pic.jpg", "http://10.0.0.1/pic.jpg"):
            with self.assertRaises(ValueError):
                app.proxy_fetch_image(bad)

    def test_blocks_invalid_urls(self):
        for bad in ("", "javascript:alert(1)", "file:///etc/passwd", "not_a_url"):
            with self.assertRaises(ValueError):
                app.proxy_fetch_image(bad)

    def test_proxy_fetch_image_success(self):
        fake_bytes = b"\xff\xd8\xff\xe0fake_jpeg_content"
        mock_resp = mock.MagicMock()
        mock_resp.headers.get_content_type.return_value = "image/jpeg"
        mock_resp.read.return_value = fake_bytes
        mock_resp.__enter__.return_value = mock_resp

        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            data, ctype = app.proxy_fetch_image("https://cdn.bsky.app/img.jpg")
            self.assertEqual(data, fake_bytes)
            self.assertEqual(ctype, "image/jpeg")

    def test_proxy_endpoint_serves_image(self):
        fake_bytes = b"\x89PNGfake_png"
        h = object.__new__(app.H)
        h.path = "/api/proxy_image?url=" + app.urllib.parse.quote("https://cdn.bsky.app/img.png")
        h.headers = {"Host": f"127.0.0.1:{app.PORT}"}
        h.wfile = io.BytesIO()
        h.sent = []
        h.send_response = lambda code: h.sent.append(("code", code))
        h.send_header = lambda k, v: h.sent.append((k, v))
        h.end_headers = lambda: None

        with mock.patch("app.proxy_fetch_image", return_value=(fake_bytes, "image/png")):
            h.do_GET()

        code = [v for k, v in h.sent if k == "code"][0]
        ct = [v for k, v in h.sent if k == "Content-Type"][0]
        cache = [v for k, v in h.sent if k == "Cache-Control"][0]
        self.assertEqual(code, 200)
        self.assertEqual(ct, "image/png")
        self.assertIn("max-age", cache)
        self.assertEqual(h.wfile.getvalue(), fake_bytes)

    def test_index_contains_i18n_elements(self):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="cfgLangSelect"', html)
        self.assertIn("const I18N =", html)
        self.assertIn("function applyI18n()", html)
        self.assertIn("function setLang(", html)

    def test_index_contains_follow_elements(self):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn(".btn-follow", html)
        self.assertIn(".btn-following", html)
        self.assertIn("async function toggleFollow", html)
        self.assertIn('api("/api/follow"', html)

    def test_index_contains_deck_view_elements(self):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="viewToggleBtn"', html)
        self.assertIn('id="cfgViewModeSelect"', html)
        self.assertIn('id="deckContainer"', html)
        self.assertIn('id="threadTimeline"', html)
        self.assertIn('id="colCompose"', html)
        self.assertIn('id="deckAddColCard"', html)
        self.assertIn('id="deckAddColBtn"', html)
        self.assertIn('id="deckAddColMenu"', html)
        self.assertIn('id="i-arrow-left"', html)
        self.assertIn('id="i-arrow-right"', html)
        self.assertIn('id="i-close"', html)
        self.assertIn('id="i-drag-grip"', html)
        self.assertIn("function applyViewMode(", html)
        self.assertIn("function applyDeckColumnVisibility(", html)
        self.assertIn("function moveDeckColumn(", html)
        self.assertIn("function closeDeckColumn(", html)
        self.assertIn("function addDeckColumn(", html)
        self.assertIn("function reorderDeckColumn(", html)
        self.assertIn("function initDeckDragAndDrop(", html)
        self.assertIn("function closeColumnThread(", html)
        self.assertIn("view_mode_single", html)
        self.assertIn("view_mode_deck", html)

    def test_index_contains_profile_hub_and_brand_action_icons(self):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="i-refresh"', html)
        self.assertIn('id="i-arrow-up"', html)
        self.assertIn('id="panelHubView"', html)
        self.assertIn('id="profileAccountsList"', html)
        self.assertIn('id="profileDetailView"', html)
        self.assertIn('id="profileBackBtn"', html)
        self.assertIn('id="profileActiveCard"', html)
        self.assertIn('id="profileActiveFeed"', html)
        self.assertIn("function renderProfileAccountsList(", html)
        self.assertIn("function viewOwnAccount(", html)
        self.assertIn("function returnFromProfileDetail(", html)
        self.assertIn("function refreshProfileView(", html)

    def test_index_contains_saved_posts_feature(self):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="i-bookmark"', html)
        self.assertIn('id="i-bookmark-fill"', html)
        self.assertIn('data-tab="saved"', html)
        self.assertIn('id="colSaved"', html)
        self.assertIn('id="pSaved"', html)
        self.assertIn('id="savedFeed"', html)
        self.assertIn('id="threadSaved"', html)
        self.assertIn('id="savedNetFilters"', html)
        self.assertIn('id="savedSearchInput"', html)
        self.assertIn('mastosky_saved_posts', html)
        self.assertIn("function getSavedPosts(", html)
        self.assertIn("function toggleSavePost(", html)
        self.assertIn("function renderSavedFeed(", html)
        self.assertIn("act-save", html)
        self.assertIn("saved_rm", html)
        self.assertIn("toast_saved", html)

    def test_index_contains_reply_box_elements(self):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="replyBox"', html)
        self.assertIn('id="replyParentAvatar"', html)
        self.assertIn('id="replyParentName"', html)
        self.assertIn('id="replyUserAvatar"', html)
        self.assertIn('id="cancelReply"', html)
        self.assertIn("function renderReplyBox(", html)
        self.assertIn("function startReply(", html)
        self.assertIn("function cancelReply(", html)
        self.assertIn(".is-reply-target", html)

    def test_scroll_anchoring_and_notification_signaling_elements(self):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
        # Scroll anchoring e pílulas de novos posts
        self.assertIn('id="timelineNewPostsPill"', html)
        self.assertIn('id="exploreNewPostsPill"', html)
        self.assertIn('id="notifsNewPostsPill"', html)
        self.assertIn(".new-posts-pill", html)
        self.assertIn("function captureScrollAnchor(", html)
        self.assertIn("function restoreScrollAnchor(", html)
        self.assertIn("function scrollColToTop(", html)
        self.assertIn("new_notifs_pill_one", html)
        self.assertIn("new_notifs_pill_many", html)
        self.assertIn('["timeline", "explore", "notifs"]', html)
        # Notificações renovadas
        self.assertIn('id="notifSummaryBanner"', html)
        self.assertIn('id="notifSummaryText"', html)
        self.assertIn(".notif-unread-dot", html)
        self.assertIn(".filter-badge", html)
        self.assertIn('id="notifBadgeAll"', html)
        self.assertIn('id="notifBadgeReplies"', html)
        self.assertIn('id="notifBadgeLikes"', html)

    def test_deck_thread_side_column_and_distinct_icons(self):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
        # Coluna lateral de conversa no modo Deck
        self.assertIn('id="colThread"', html)
        self.assertIn('class="deck-col deck-col-thread"', html)
        self.assertIn('id="deckThreadBackBtn"', html)
        self.assertIn('id="deckThreadTitle"', html)
        self.assertIn('id="colThreadBody"', html)
        self.assertIn('id="deckThreadContent"', html)
        self.assertIn("function closeDeckThread(", html)
        self.assertIn("function deckThreadBack(", html)
        self.assertIn(".is-thread-active", html)
        self.assertIn(".clickable-post", html)
        # Suporte a clique em posts em todas as colunas incluindo Notificações
        self.assertIn("openThread(targetPost, false, p)", html)
        self.assertIn("p.classList.add(\"clickable-post\")", html)
        self.assertIn('id="threadNotifs"', html)
        # Ações completas nos cartões de notificação (like, repost, bookmark, reply, thread)
        self.assertIn("act-boost", html)
        self.assertIn("act-like", html)
        self.assertIn("openBoostMenu(postTarget, bB)", html)
        self.assertIn("act(postTarget, \"like\", bL)", html)
        self.assertIn("toggleSavePost(postTarget, bS)", html)
        # Ícones distintos para responder e ver conversa
        # Responder: seta curva
        self.assertIn('reply: \'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/>', html)
        # Conversa: nós/cadeia conectados
        self.assertIn('thread: \'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="5" r="2.5"/><line x1="12" y1="7.5" x2="12" y2="16.5" stroke-dasharray="2 2"/>', html)

    def test_crosspost_card_enhancements(self):
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
        # Funções de renderização aprimorada de crosspost
        self.assertIn("function getCanvasWrappedLines(", html)
        self.assertIn("async function drawQuotedCard(", html)
        self.assertIn("async function renderCrossCanvas(", html)
        self.assertIn("/brand/logo-lockup-dark.svg", html)
        # Suporte a posts citados dentro do cartão
        self.assertIn("it.quote", html)
        self.assertIn("drawQuotedCard(ctx, it.quote", html)
        # Botões de tema 100% redondos e sem artefatos
        self.assertIn(".swatch{width:28px;height:28px;border-radius:50%!important", html)
        self.assertIn("background-clip:padding-box", html)

    def test_index_javascript_syntax_valid(self):
        import shutil, subprocess, re
        node_bin = shutil.which("node")
        if not node_bin:
            return
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()
        m = re.search(r"<script>([\s\S]*?)</script>", html)
        self.assertIsNotNone(m, "Bloco <script> não encontrado no index.html")
        js_code = m.group(1)
        # Passar código via stdin para evitar exceder o limite de argumentos do kernel Linux (MAX_ARG_STRLEN = 128KB)
        res = subprocess.run([node_bin, "-e", "const fs = require('fs'); new Function(fs.readFileSync(0, 'utf-8'));"],
                             input=js_code, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Erro de sintaxe no JavaScript do index.html: {res.stderr}")

    def test_parse_semver(self):
        self.assertEqual(app.parse_semver("0.3.0"), [0, 3, 0])
        self.assertEqual(app.parse_semver("v1.2.3"), [1, 2, 3])
        self.assertTrue(app.parse_semver("0.4.0") > app.parse_semver("0.3.0"))
        self.assertFalse(app.parse_semver("0.3.0") > app.parse_semver("0.3.0"))

    def test_api_version_endpoint(self):
        import io
        h = object.__new__(app.H)
        h.path = "/api/version"
        h.headers = {"Host": "127.0.0.1:%d" % app.PORT}
        h.wfile = io.BytesIO()
        h.sent = []
        h.send_response = lambda code: h.sent.append(("code", code))
        h.send_header = lambda k, v: h.sent.append((k, v))
        h.end_headers = lambda: None
        h.do_GET()
        code = [v for k, v in h.sent if k == "code"][0]
        self.assertEqual(code, 200)
        data = json.loads(h.wfile.getvalue())
        self.assertIn("current", data)
        self.assertIn("latest", data)
        self.assertIn("has_update", data)

    def test_self_update_endpoint_requires_csrf(self):
        import io
        h = object.__new__(app.H)
        h.path = "/api/self_update"
        h.headers = {"Host": "127.0.0.1:%d" % app.PORT, "Content-Length": "2"}
        h.rfile = io.BytesIO(b"{}")
        h.wfile = io.BytesIO()
        h.sent = []
        h.send_response = lambda code: h.sent.append(("code", code))
        h.send_header = lambda k, v: h.sent.append((k, v))
        h.end_headers = lambda: None
        h.do_POST()
        code = [v for k, v in h.sent if k == "code"][0]
        self.assertEqual(code, 403)

    def test_local_image_endpoint(self):
        import io, tempfile, urllib.parse
        # Criar imagem temporária válida dentro da diretoria do projeto
        with tempfile.NamedTemporaryFile(suffix=".png", dir=str(app.DIR), delete=False) as tf:
            tf.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")
            tmp_path = tf.name
        try:
            h = object.__new__(app.H)
            h.path = "/api/local_image?path=" + urllib.parse.quote(tmp_path)
            h.headers = {"Host": "127.0.0.1:%d" % app.PORT}
            h.wfile = io.BytesIO()
            h.sent = []
            h.send_response = lambda code: h.sent.append(("code", code))
            h.send_header = lambda k, v: h.sent.append((k, v))
            h.end_headers = lambda: None
            h.do_GET()
            code = [v for k, v in h.sent if k == "code"][0]
            self.assertEqual(code, 200)

            # Teste ficheiro com extensão inválida
            h_bad = object.__new__(app.H)
            h_bad.path = "/api/local_image?path=/tmp/test.sh"
            h_bad.headers = {"Host": "127.0.0.1:%d" % app.PORT}
            h_bad.wfile = io.BytesIO()
            h_bad.sent = []
            h_bad.send_response = lambda code: h_bad.sent.append(("code", code))
            h_bad.send_header = lambda k, v: h_bad.sent.append((k, v))
            h_bad.end_headers = lambda: None
            h_bad.do_GET()
            code_bad = [v for k, v in h_bad.sent if k == "code"][0]
            self.assertIn(code_bad, (400, 403))
        finally:
            import os
            try: os.unlink(tmp_path)
            except OSError: pass


if __name__ == "__main__":
    unittest.main()

