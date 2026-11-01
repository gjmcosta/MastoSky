"""Testes unitários dos parsers do MastoSky. Sem rede e sem config.json."""
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


if __name__ == "__main__":
    unittest.main()
