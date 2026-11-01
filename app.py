#!/usr/bin/env python3
"""Timeline unificada Bluesky + Mastodon. Corre só no teu Mac (127.0.0.1)."""
import base64, binascii, html, json, os, re, socket, stat, threading, time, urllib.error, urllib.parse, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIR = Path(__file__).parent
CFG_PATH = DIR / "config.json"


def secure_config_perms(path=None):
    """Garante permissões 0600 (só o dono lê/escreve). Silencioso onde não é suportado (Windows)."""
    path = path or CFG_PATH
    try:
        if stat.S_IMODE(os.stat(path).st_mode) & 0o077:
            os.chmod(path, 0o600)
    except OSError:
        pass


def write_config(cfg, path=None):
    """Grava o config com permissões 0600 desde a criação (sem janela em que fique legível por outros)."""
    path = path or CFG_PATH
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(cfg, indent=2))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_cfg():
    if CFG_PATH.exists():
        secure_config_perms()
        try:
            return json.loads(CFG_PATH.read_text())
        except Exception:
            return {}
    return {}


MAX_BODY = 32 * 1024 * 1024  # limite do corpo dos pedidos POST (imagens em base64)
CFG = load_cfg()
PORT = CFG.get("port", 8000)


def multipart_encode(fields, files):
    boundary = f"----MastoSky{uuid.uuid4().hex}"
    body = bytearray()
    for name, val in fields.items():
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n".encode())
    for name, (filename, file_bytes, ctype) in files.items():
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n".encode())
        body.extend(file_bytes)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


class ApiError(RuntimeError):
    """Erro de API. `str(e)` mantém o formato "{código}: ..." de que o resto do código depende."""
    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _retry_after(headers):
    try:
        v = headers.get("Retry-After") if headers else None
        return max(0, int(float(v))) if v is not None else None
    except (TypeError, ValueError):
        return None


RETRY_MAX_WAIT = 5  # segundos: só repete um GET num 429 se o servidor pedir menos do que isto


def http(method, url, data=None, token=None, headers=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", "timeline-unificada/1.0")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    body = None
    if data is not None:
        if isinstance(data, (bytes, bytearray)):
            body = data
            if not headers or "Content-Type" not in headers:
                req.add_header("Content-Type", "application/octet-stream")
        else:
            body = json.dumps(data).encode()
            if not headers or "Content-Type" not in headers:
                req.add_header("Content-Type", "application/json")
    host = urllib.parse.urlparse(url).netloc
    for attempt in (0, 1):
        try:
            with urllib.request.urlopen(req, body, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            ra = _retry_after(e.headers)
            if e.code == 429 and method == "GET" and attempt == 0 and ra is not None and ra <= RETRY_MAX_WAIT:
                time.sleep(ra)
                continue
            msg = f"{e.code}: {e.read()[:200].decode(errors='replace')}"
            if e.code == 429:
                msg += f" (limite de pedidos; tenta de novo{f' dentro de {ra} s' if ra is not None else ' mais tarde'})"
            raise ApiError(msg, status=e.code, retry_after=ra)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            raise ApiError(f"Sem ligação a {host}: {reason}")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def sort_items(items):
    return sorted(items, key=lambda i: parse_time(i.get("time")), reverse=True)


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_TIME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?\s*(Z|[+-]\d{2}(?::?\d{2})?)?$", re.I)


def parse_time(s):
    """ISO 8601 → datetime com fuso. Tolera 'Z', offsets e qualquer nº de casas decimais.
    Valor inválido → época 0 (vai para o fim da timeline)."""
    if not isinstance(s, str):
        return _EPOCH
    m = _TIME_RE.match(s.strip())
    if not m:
        return _EPOCH
    y, mo, d, h, mi, sec, frac, tz = m.groups()
    try:
        micro = int((frac or "0")[:6].ljust(6, "0"))
        if not tz or tz.upper() == "Z":
            tzinfo = timezone.utc
        else:
            sign = -1 if tz[0] == "-" else 1
            digits = tz[1:].replace(":", "")
            off = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0))
            tzinfo = timezone(sign * off)
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec or 0), micro, tzinfo=tzinfo)
    except (ValueError, OverflowError):
        return _EPOCH


def linkify(text):
    return re.sub(r"(https?://[^\s<]+)", r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
                  html.escape(text)).replace("\n", "<br>")


class Clean(HTMLParser):
    """Limpa o HTML que vem do Mastodon: só fica texto, <br> e links http(s)."""
    def __init__(s, strip_quote_inline=False):
        super().__init__()
        s.o, s.sp, s.hide = [], [], 0
        s.strip_quote_inline = strip_quote_inline
        s.quote_inline_depth = 0

    def handle_starttag(s, t, a):
        a = dict(a)
        if s.strip_quote_inline and ("quote-inline" in (a.get("class") or "")):
            s.quote_inline_depth += 1
            s.hide += 1
            return
        if s.quote_inline_depth > 0:
            if t in ("p", "div", "span", "a"):
                s.quote_inline_depth += 1
            return
        if t == "p" and s.o:
            s.o.append("<br><br>")
        elif t == "br":
            s.o.append("<br>")
        elif t == "span":
            s.sp.append("invisible" in (a.get("class") or ""))
            s.hide += s.sp[-1]
        elif t == "a":
            h = a.get("href") or ""
            ok = h.startswith(("http://", "https://"))
            s.o.append(f'<a href="{html.escape(h, True)}" target="_blank" rel="noopener noreferrer">' if ok else "<a>")

    def handle_endtag(s, t):
        if s.quote_inline_depth > 0:
            s.quote_inline_depth -= 1
            if s.quote_inline_depth == 0:
                s.hide -= 1
            return
        if t == "a":
            s.o.append("</a>")
        elif t == "span" and s.sp:
            s.hide -= s.sp.pop()

    def handle_data(s, d):
        if not s.hide:
            s.o.append(html.escape(d))


def clean(h, strip_quote_inline=False):
    c = Clean(strip_quote_inline=strip_quote_inline)
    c.feed(h or "")
    return "".join(c.o)


def preview(text, n=140):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


def plain(h):
    return html.unescape(re.sub(r"<[^>]+>", " ", clean(h)))


def safe_url(u):
    """Só devolve URLs http(s) absolutos; qualquer outra coisa (javascript:, data:, //x) dá None."""
    if not isinstance(u, str):
        return None
    u = u.strip()
    try:
        p = urllib.parse.urlparse(u)
    except ValueError:
        return None
    return u if p.scheme in ("http", "https") and p.netloc else None


def safe_media(m):
    """Sanitiza os URLs de um item de media; devolve None se ficar inutilizável."""
    url, thumb = safe_url(m.get("url")), safe_url(m.get("thumb"))
    if m.get("type") in ("image", "video", "gifv"):
        url = url or thumb
        if not url:
            return None
    elif m.get("type") == "external" and not url:
        return None
    out = dict(m)
    out["url"], out["thumb"] = url, thumb
    return out


def safe_media_list(items):
    return [x for x in (safe_media(m) for m in items) if x]


def extract_bsky_embed(embed):
    media, quote = _extract_bsky_embed(embed)
    return safe_media_list(media), quote


def _extract_bsky_embed(embed):
    media = []
    quote = None
    if not embed:
        return media, quote
    etype = embed.get("$type", "")

    if etype == "app.bsky.embed.images#view":
        for i in embed.get("images", []):
            media.append({
                "type": "image",
                "url": i.get("fullsize") or i.get("thumb"),
                "thumb": i.get("thumb") or i.get("fullsize"),
                "alt": i.get("alt", "")
            })
    elif etype == "app.bsky.embed.video#view":
        media.append({
            "type": "video",
            "url": embed.get("playlist"),
            "thumb": embed.get("thumbnail"),
            "alt": embed.get("alt", "")
        })
    elif etype == "app.bsky.embed.external#view":
        ext = embed.get("external") or {}
        if ext.get("thumb") or ext.get("uri"):
            media.append({
                "type": "external",
                "url": ext.get("uri"),
                "thumb": ext.get("thumb"),
                "title": ext.get("title", ""),
                "description": ext.get("description", "")
            })
    elif etype == "app.bsky.embed.recordWithMedia#view":
        m_list, _ = extract_bsky_embed(embed.get("media"))
        media.extend(m_list)
        rec_obj = embed.get("record")
        quote = parse_bsky_quote(rec_obj)
    elif etype == "app.bsky.embed.record#view":
        rec_obj = embed.get("record")
        quote = parse_bsky_quote(rec_obj)

    return media, quote


def parse_bsky_quote(rec):
    if not rec:
        return None
    # Desembrulha caso venha envolvido em { "record": { ... } }
    if isinstance(rec, dict) and "record" in rec and isinstance(rec["record"], dict):
        rec = rec["record"]
    rtype = rec.get("$type")
    if rtype == "app.bsky.embed.record#viewNotFound":
        return {
            "network": "bluesky",
            "name": "Publicação indisponível",
            "handle": "",
            "avatar": None,
            "html": "<em>Esta publicação foi apagada.</em>",
            "url": None,
            "media": []
        }
    if rtype == "app.bsky.embed.record#viewBlocked":
        return {
            "network": "bluesky",
            "name": "Publicação bloqueada",
            "handle": "",
            "avatar": None,
            "html": "<em>Esta publicação é de uma conta que foi bloqueada.</em>",
            "url": None,
            "media": []
        }
    if rtype != "app.bsky.embed.record#viewRecord":
        return None
    author = rec.get("author") or {}
    val = rec.get("value") or {}
    handle = author.get("handle") or ""
    q_media = []
    emb_list = rec.get("embeds") or []
    if not emb_list and rec.get("embed"):
        emb_list = [rec.get("embed")]
    for emb in emb_list:
        m_list, _ = extract_bsky_embed(emb)
        q_media.extend(m_list)
    text = val.get("text") or rec.get("text", "")
    return {
        "network": "bluesky",
        "name": author.get("displayName") or handle,
        "handle": "@" + handle if handle else "",
        "avatar": safe_url(author.get("avatar")),
        "html": linkify(text) if text else "",
        "time": val.get("createdAt") or rec.get("createdAt") or rec.get("indexedAt"),
        "url": f"https://bsky.app/profile/{handle}/post/{rec.get('uri', '').split('/')[-1]}" if handle else None,
        "media": q_media
    }


def parse_masto_quote(st):
    if not st or not isinstance(st, dict):
        return None
    q_data = st.get("quote") or st.get("quoted_status")
    if not q_data:
        return None
    if isinstance(q_data, dict) and "quoted_status" in q_data:
        state = q_data.get("state")
        if state and state not in ("accepted", "pending"):
            return None
        qs = q_data.get("quoted_status")
    elif isinstance(q_data, dict):
        qs = q_data
    else:
        return None

    if not qs or not isinstance(qs, dict):
        return None

    q_acc = qs.get("account") or {}
    q_media = []
    for m in qs.get("media_attachments", []):
        mtype = m.get("type")
        if mtype in ("image", "video", "gifv"):
            q_media.append({
                "type": mtype,
                "url": m.get("url") or m.get("preview_url"),
                "thumb": m.get("preview_url") or m.get("url"),
                "alt": m.get("description") or ""
            })
    if not q_media and qs.get("card") and qs["card"].get("url"):
        card = qs["card"]
        q_media.append({
            "type": "external",
            "url": card.get("url"),
            "thumb": card.get("image"),
            "title": card.get("title", ""),
            "description": card.get("description", "")
        })

    cw = f"<strong>{html.escape(qs['spoiler_text'])}</strong><br>" if qs.get("spoiler_text") else ""
    q_html = cw + clean(qs.get("content"), strip_quote_inline=True)
    q_html = re.sub(r"^\s*RE:\s*<a\b[^>]*>.*?</a>(\s*<br\s*/?>\s*)*", "", q_html, flags=re.I)
    q_html = re.sub(r"(\s*<br\s*/?>\s*)*\s*RE:\s*<a\b[^>]*>.*?</a>\s*$", "", q_html, flags=re.I).strip()

    return {
        "network": "mastodon",
        "name": q_acc.get("display_name") or q_acc.get("username", ""),
        "handle": "@" + q_acc.get("acct", ""),
        "avatar": safe_url(q_acc.get("avatar")),
        "html": q_html,
        "time": qs.get("created_at"),
        "url": safe_url(qs.get("url")),
        "media": safe_media_list(q_media)
    }


class Bsky:
    name = "bluesky"

    def __init__(s, c):
        s.c, s.jwt, s.refresh_jwt, s.did = c, None, None, None
        s.host = c.get("service", "https://bsky.social")
        s.lock = threading.RLock()  # protege login/refresh em pedidos concorrentes

    def login(s):
        with s.lock:
            r = http("POST", s.host + "/xrpc/com.atproto.server.createSession",
                     {"identifier": s.c["handle"], "password": s.c["app_password"]})
            s.jwt, s.refresh_jwt, s.did = r["accessJwt"], r.get("refreshJwt"), r["did"]

    def _ensure(s):
        with s.lock:
            if not s.jwt:
                s.login()

    def _renew(s, failed_jwt):
        """Renova a sessão: primeiro refreshSession; só se falhar volta a createSession."""
        with s.lock:
            if s.jwt != failed_jwt:  # outro pedido já renovou entretanto
                return
            if s.refresh_jwt:
                try:
                    r = http("POST", s.host + "/xrpc/com.atproto.server.refreshSession", token=s.refresh_jwt)
                    s.jwt, s.refresh_jwt = r["accessJwt"], r.get("refreshJwt") or s.refresh_jwt
                    s.did = r.get("did") or s.did
                    return
                except (RuntimeError, KeyError):
                    pass
            s.jwt = None
            s.login()

    @staticmethod
    def _expired(e):
        return "ExpiredToken" in str(e) or str(e).startswith("401")

    def _authed(s, fn):
        """Executa fn(jwt); se o token expirou, renova a sessão e repete uma vez."""
        s._ensure()
        jwt = s.jwt
        try:
            return fn(jwt)
        except RuntimeError as e:
            if not s._expired(e):
                raise
            s._renew(jwt)
            return fn(s.jwt)

    def call(s, method, nsid, data=None, params=None):
        url = f"{s.host}/xrpc/{nsid}" + ("?" + urllib.parse.urlencode(params) if params else "")
        return s._authed(lambda jwt: http(method, url, data, jwt))

    def item(s, p, reason=None, reply=None):
        a, rec = p["author"], p["record"]
        root = rec.get("reply", {}).get("root") or {"uri": p["uri"], "cid": p["cid"]}
        media, quote = [], None
        embed_sources = []
        if p.get("embed"):
            embed_sources.append(p.get("embed"))
        for emb in p.get("embeds") or []:
            if emb not in embed_sources:
                embed_sources.append(emb)
        for emb in embed_sources:
            m_list, q_obj = extract_bsky_embed(emb)
            media.extend(m_list)
            if q_obj and not quote:
                quote = q_obj
        dedup_media, seen_urls = [], set()
        for m in media:
            u = m.get("url") or m.get("thumb")
            if u not in seen_urls:
                seen_urls.add(u)
                dedup_media.append(m)
        media = dedup_media
        reason = reason or {}
        by = reason.get("by") or {}
        rt = None
        if reply:  # só a timeline traz o contexto do post a que se responde
            par = reply.get("parent") or {}
            if par.get("author") and par.get("record"):
                rt = {"name": par["author"].get("displayName") or par["author"]["handle"],
                      "handle": "@" + par["author"]["handle"], "text": preview(par["record"].get("text", ""))}
            else:
                rt = {"name": None, "handle": None, "text": ""}
        return {
            "network": "bluesky", "name": a.get("displayName") or a["handle"], "handle": "@" + a["handle"],
            "avatar": safe_url(a.get("avatar")), "html": linkify(rec.get("text", "")),
            "time": reason.get("indexedAt") or p.get("indexedAt") or rec["createdAt"],
            "boosted_by": by.get("displayName") or by.get("handle"), "reply_to": rt,
            "media": media,
            "quote": quote,
            "replies": p.get("replyCount", 0), "boosts": p.get("repostCount", 0), "likes": p.get("likeCount", 0),
            "url": f"https://bsky.app/profile/{a['handle']}/post/{p['uri'].split('/')[-1]}",
            "ref": {"uri": p["uri"], "cid": p["cid"], "root": {"uri": root["uri"], "cid": root["cid"]}},
            "is_reply": bool(rec.get("reply")),
        }

    def timeline(s):
        feed = s.call("GET", "app.bsky.feed.getTimeline", params={"limit": 40})["feed"]
        return [s.item(it["post"], it.get("reason"), it.get("reply")) for it in feed]

    def explore(s):
        feed_uri = "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/whats-hot"
        feed = s.call("GET", "app.bsky.feed.getFeed", params={"feed": feed_uri, "limit": 40})["feed"]
        return [s.item(it["post"], it.get("reason"), it.get("reply")) for it in feed]

    def thread(s, ref):
        ok = "app.bsky.feed.defs#threadViewPost"
        r = s.call("GET", "app.bsky.feed.getPostThread",
                   params={"uri": ref["uri"], "depth": 8, "parentHeight": 30})["thread"]
        if r.get("$type") != ok:
            raise RuntimeError("Post não disponível (apagado ou bloqueado).")
        ancestors, n = [], r.get("parent")
        while n and n.get("$type") == ok:
            ancestors.insert(0, s.item(n["post"]))
            n = n.get("parent")

        def tree(node):
            out = []
            for c in node.get("replies") or []:
                if c.get("$type") == ok:
                    i = s.item(c["post"])
                    i["children"] = tree(c)
                    out.append(i)
            return out
        return {"ancestors": ancestors, "focus": s.item(r["post"]), "replies": tree(r)}

    def upload_blob(s, raw_bytes, mime="image/jpeg"):
        url = f"{s.host}/xrpc/com.atproto.repo.uploadBlob"
        r = s._authed(lambda jwt: http("POST", url, data=raw_bytes, token=jwt, headers={"Content-Type": mime}))
        return r["blob"]

    def post(s, text, ref=None, images=None, spoiler=None, poll=None):
        s._ensure()
        final_text = (text or "").strip()
        if poll and poll.get("options"):
            opts = [o.strip() for o in poll["options"] if o.strip()]
            if opts:
                dur = int(poll.get("expires_in", 86400))
                dur_str = f"{dur // 86400}d" if dur >= 86400 else f"{dur // 3600}h"
                poll_lines = [f"\n\n📊 Sondagem ({dur_str}):"]
                for i, opt in enumerate(opts):
                    poll_lines.append(f"\n{i+1}️⃣ {opt}")
                final_text = (final_text + "".join(poll_lines)).strip()
        if spoiler:
            final_text = f"⚠️ [CW: {spoiler}]\n\n{final_text}".strip()
        facets = []
        for m in re.finditer(r"https?://[^\s]+", final_text):
            url = m.group().rstrip(".,;:!?)")
            b = len(final_text[:m.start()].encode())
            facets.append({"index": {"byteStart": b, "byteEnd": b + len(url.encode())},
                           "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]})
        rec = {"$type": "app.bsky.feed.post", "text": final_text, "createdAt": now_iso()}
        if facets:
            rec["facets"] = facets
        if spoiler:
            rec["labels"] = {"$type": "com.atproto.label.defs#selfLabels", "values": [{"val": "spoiler"}]}
        if ref:
            rec["reply"] = {"root": ref["root"], "parent": {"uri": ref["uri"], "cid": ref["cid"]}}
        if images:
            embed_imgs = []
            for img in images:
                blob = s.upload_blob(img["bytes"], img.get("mime", "image/jpeg"))
                item = {"alt": img.get("alt", "") or "", "image": blob}
                if img.get("aspectRatio"):
                    item["aspectRatio"] = img["aspectRatio"]
                embed_imgs.append(item)
            rec["embed"] = {"$type": "app.bsky.embed.images", "images": embed_imgs}
        s.call("POST", "com.atproto.repo.createRecord",
               {"repo": s.did, "collection": "app.bsky.feed.post", "record": rec})

    def act(s, action, ref):
        s._ensure()
        col = {"like": "app.bsky.feed.like", "boost": "app.bsky.feed.repost"}[action]
        s.call("POST", "com.atproto.repo.createRecord", {
            "repo": s.did, "collection": col,
            "record": {"$type": col, "subject": {"uri": ref["uri"], "cid": ref["cid"]}, "createdAt": now_iso()}})

    def notifications(s):
        kinds = {"like": "like", "like-via-repost": "like", "repost": "boost", "repost-via-repost": "boost",
                 "follow": "follow", "mention": "mention", "reply": "reply", "quote": "quote"}
        ns = s.call("GET", "app.bsky.notification.listNotifications", params={"limit": 40})["notifications"]
        subjects = sorted({n["reasonSubject"] for n in ns
                           if n.get("reasonSubject") and kinds.get(n["reason"]) in ("like", "boost")})
        posts = {}
        for i in range(0, len(subjects), 25):
            r = s.call("GET", "app.bsky.feed.getPosts", params=[("uris", u) for u in subjects[i:i + 25]])
            for p in r.get("posts", []):
                posts[p["uri"]] = p
        out = []
        for n in ns:
            kind, a = kinds.get(n["reason"], "other"), n["author"]
            subject = posts.get(n.get("reasonSubject"))
            ref, text, url = None, "", f"https://bsky.app/profile/{a['handle']}"
            if kind in ("reply", "mention", "quote"):
                rec = n["record"]
                text = rec.get("text", "")
                root = rec.get("reply", {}).get("root") or {"uri": n["uri"], "cid": n["cid"]}
                ref = {"uri": n["uri"], "cid": n["cid"], "root": {"uri": root["uri"], "cid": root["cid"]}}
                url = f"https://bsky.app/profile/{a['handle']}/post/{n['uri'].split('/')[-1]}"
            elif subject:
                text = subject["record"].get("text", "")
                url = f"https://bsky.app/profile/{subject['author']['handle']}/post/{subject['uri'].split('/')[-1]}"
            out.append({"network": "bluesky", "kind": kind, "name": a.get("displayName") or a["handle"],
                        "handle": "@" + a["handle"], "avatar": safe_url(a.get("avatar")),
                        "html": linkify(text) if text else "", "time": n["indexedAt"], "url": url, "ref": ref})
        return out


class Masto:
    name = "mastodon"

    def __init__(s, c):
        s.base, s.token = c["instance"].rstrip("/"), c["token"]
        s.cache = {}  # posts "pai" já obtidos

    def call(s, method, path, data=None, params=None):
        url = s.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        return http(method, url, data, s.token)

    def parent(s, sid):
        if sid in s.cache:
            return s.cache[sid]
        try:
            p = s.call("GET", f"/api/v1/statuses/{sid}")
        except Exception:
            return None
        if len(s.cache) > 500:
            s.cache.clear()
        s.cache[sid] = p
        return p

    def reply_info(s, p):
        if not p:
            return {"name": None, "handle": None, "text": ""}
        a = p["account"]
        return {"name": a.get("display_name") or a["username"], "handle": "@" + a["acct"],
                "text": preview(p.get("spoiler_text") or plain(p.get("content")))}

    def item(s, st, parents=None):
        x = st.get("reblog") or st
        a = x["account"]
        rt = None
        if parents is not None and x.get("in_reply_to_id"):
            rt = s.reply_info(parents.get(x["in_reply_to_id"]))
        cw = f"<strong>{html.escape(x['spoiler_text'])}</strong><br>" if x.get("spoiler_text") else ""
        quote = parse_masto_quote(x)
        raw_html = clean(x.get("content"), strip_quote_inline=bool(quote))
        if quote:
            raw_html = re.sub(r"^\s*RE:\s*<a\b[^>]*>.*?</a>(\s*<br\s*/?>\s*)*", "", raw_html, flags=re.I)
            raw_html = re.sub(r"(\s*<br\s*/?>\s*)*\s*RE:\s*<a\b[^>]*>.*?</a>\s*$", "", raw_html, flags=re.I).strip()

        media = []
        for m in x.get("media_attachments", []):
            mtype = m.get("type")
            if mtype in ("image", "video", "gifv"):
                media.append({
                    "type": mtype,
                    "url": m.get("url") or m.get("preview_url"),
                    "thumb": m.get("preview_url") or m.get("url"),
                    "alt": m.get("description") or ""
                })
        if not media and not quote and x.get("card") and x["card"].get("url"):
            card = x["card"]
            media.append({
                "type": "external",
                "url": card.get("url"),
                "thumb": card.get("image"),
                "title": card.get("title", ""),
                "description": card.get("description", "")
            })
        return {
            "network": "mastodon", "name": a.get("display_name") or a["username"], "handle": "@" + a["acct"],
            "avatar": safe_url(a.get("avatar")), "html": cw + raw_html,
            "time": st["created_at"],
            "boosted_by": (st["account"].get("display_name") or st["account"]["username"]) if st.get("reblog") else None,
            "media": safe_media_list(media),
            "quote": quote,
            "replies": x.get("replies_count", 0), "boosts": x.get("reblogs_count", 0), "likes": x.get("favourites_count", 0),
            "url": safe_url(x.get("url")), "ref": {"id": x["id"]}, "reply_to": rt,
            "is_reply": bool(x.get("in_reply_to_id")),
        }

    def timeline(s):
        sts = s.call("GET", "/api/v1/timelines/home", params={"limit": 40})
        parents = {x["id"]: x for x in (st.get("reblog") or st for st in sts)}
        need = list({x["in_reply_to_id"] for x in parents.values() if x.get("in_reply_to_id")} - set(parents))
        with ThreadPoolExecutor(max_workers=6) as ex:
            for sid, par in zip(need, ex.map(s.parent, need)):
                if par:
                    parents[sid] = par
        return [s.item(st, parents) for st in sts]

    def explore(s):
        sts = s.call("GET", "/api/v1/trends/statuses", params={"limit": 40})
        parents = {x["id"]: x for x in (st.get("reblog") or st for st in sts)}
        need = list({x["in_reply_to_id"] for x in parents.values() if x.get("in_reply_to_id")} - set(parents))
        with ThreadPoolExecutor(max_workers=6) as ex:
            for sid, par in zip(need, ex.map(s.parent, need)):
                if par:
                    parents[sid] = par
        return [s.item(st, parents) for st in sts]

    def thread(s, ref):
        st = s.call("GET", f"/api/v1/statuses/{ref['id']}")
        c = s.call("GET", f"/api/v1/statuses/{ref['id']}/context")
        nodes = {}
        for d in c["descendants"]:
            i = s.item(d)
            i["children"] = []
            nodes[d["id"]] = i
        replies = []
        for d in c["descendants"]:
            parent = nodes.get(d.get("in_reply_to_id"))
            (parent["children"] if parent else replies).append(nodes[d["id"]])
        return {"ancestors": [s.item(x) for x in c["ancestors"]], "focus": s.item(st), "replies": replies}

    def upload_media(s, raw_bytes, mime="image/jpeg", description=""):
        ext = mime.split("/")[-1] if "/" in mime else "jpg"
        data, ctype = multipart_encode({"description": description or ""},
                                       {"file": (f"media.{ext}", raw_bytes, mime)})
        r = http("POST", s.base + "/api/v2/media", data=data, token=s.token,
                 headers={"Content-Type": ctype})
        return r["id"]

    def post(s, text, ref=None, images=None, spoiler=None, poll=None):
        media_ids = []
        if images:
            for img in images:
                mid = s.upload_media(img["bytes"], img.get("mime", "image/jpeg"), img.get("alt", ""))
                media_ids.append(mid)
        data = {"status": text or ""}
        if spoiler:
            data["spoiler_text"] = spoiler
        if poll and poll.get("options"):
            opts = [o.strip() for o in poll["options"] if o.strip()]
            if len(opts) >= 2:
                data["poll"] = {
                    "options": opts,
                    "expires_in": int(poll.get("expires_in", 86400)),
                    "multiple": False
                }
        if media_ids:
            data["media_ids"] = media_ids
        if ref:
            data["in_reply_to_id"] = ref["id"]
        s.call("POST", "/api/v1/statuses", data)

    def act(s, action, ref):
        s.call("POST", f"/api/v1/statuses/{ref['id']}/" + {"like": "favourite", "boost": "reblog"}[action])

    def notifications(s):
        kinds = {"favourite": "like", "reblog": "boost", "follow": "follow", "follow_request": "follow_request",
                 "mention": "mention", "quote": "quote", "status": "status", "update": "update", "poll": "poll"}
        out = []
        for n in s.call("GET", "/api/v1/notifications", params={"limit": 40}):
            a, st = n["account"], n.get("status")
            kind = kinds.get(n["type"], "other")
            if kind == "mention" and st and st.get("in_reply_to_id"):
                kind = "reply"
            cw = f"<strong>{html.escape(st['spoiler_text'])}</strong><br>" if st and st.get("spoiler_text") else ""
            out.append({"network": "mastodon", "kind": kind, "name": a.get("display_name") or a["username"],
                        "handle": "@" + a["acct"], "avatar": safe_url(a.get("avatar")),
                        "html": (cw + clean(st.get("content"))) if st else "", "time": n["created_at"],
                        "url": safe_url((st or {}).get("url") or a.get("url")),
                        "ref": {"id": st["id"]} if st and kind in ("reply", "mention", "quote") else None})
        return out


def init_clients(cfg):
    clients = {}
    if cfg.get("bluesky", {}).get("handle") and cfg.get("bluesky", {}).get("app_password"):
        clients["bluesky"] = Bsky(cfg["bluesky"])
    if cfg.get("mastodon", {}).get("token") and cfg.get("mastodon", {}).get("instance"):
        clients["mastodon"] = Masto(cfg["mastodon"])
    return clients


CLIENTS = init_clients(CFG)


# 'unsafe-inline' necessário porque a UI é um único ficheiro com <script>/<style> inline.
# connect-src/worker-src https:/blob: são exigidos pelo hls.js (playlists e segmentos de vídeo do Bluesky).
CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src https: data: blob:; media-src https: blob:; connect-src 'self' https:; worker-src blob:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class H(BaseHTTPRequestHandler):
    def log_message(s, *a):
        pass

    def allowed(s):
        # Protege contra outros sites a falarem com o servidor local.
        ok = (f"127.0.0.1:{PORT}", f"localhost:{PORT}")
        o = s.headers.get("Origin")
        return s.headers.get("Host") in ok and (o is None or o in [f"http://{h}" for h in ok])

    def send(s, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        s.send_response(code)
        s.send_header("Content-Type", ctype + "; charset=utf-8")
        s.send_header("Content-Length", str(len(b)))
        s.send_header("X-Content-Type-Options", "nosniff")
        s.send_header("Referrer-Policy", "no-referrer")
        s.send_header("X-Frame-Options", "DENY")
        s.send_header("Content-Security-Policy", CSP)
        s.end_headers()
        s.wfile.write(b)

    def do_GET(s):
        if not s.allowed():
            return s.send(403, {"error": "forbidden"})
        if s.path == "/":
            return s.send(200, (DIR / "index.html").read_bytes(), "text/html")
        if s.path == "/vendor/hls.min.js":
            return s.send(200, (DIR / "vendor" / "hls.min.js").read_bytes(), "application/javascript")
        if s.path == "/api/status":
            return s.send(200, {
                "configured": bool(CLIENTS),
                "networks": list(CLIENTS),
                "bluesky": {
                    "configured": "bluesky" in CLIENTS,
                    "handle": CFG.get("bluesky", {}).get("handle", "")
                },
                "mastodon": {
                    "configured": "mastodon" in CLIENTS,
                    "instance": CFG.get("mastodon", {}).get("instance", "")
                }
            })
        if s.path in ("/api/timeline", "/api/notifications", "/api/explore"):
            if not CLIENTS:
                return s.send(200, {"items": [], "errors": {}, "networks": []})
            what = s.path.rsplit("/", 1)[1]
            network_items, errors = {}, {}

            def get(c):
                try:
                    return c.name, getattr(c, what)(), None
                except Exception as e:
                    return c.name, [], str(e)
            with ThreadPoolExecutor() as ex:
                for name, its, err in ex.map(get, CLIENTS.values()):
                    network_items[name] = its
                    if err:
                        errors[name] = err
            if what == "explore":
                items = []
                lists = list(network_items.values())
                idx = 0
                while any(idx < len(l) for l in lists):
                    for l in lists:
                        if idx < len(l):
                            items.append(l[idx])
                    idx += 1
            else:
                items = []
                for its in network_items.values():
                    items += its
                items = sort_items(items)
            return s.send(200, {"items": items, "errors": errors, "networks": list(CLIENTS)})
        s.send(404, {"error": "not found"})

    def do_POST(s):
        try:
            s._do_post()
        except Exception:
            # Resposta genérica: nunca expor tracebacks nem segredos.
            try:
                s.send(500, {"error": "Erro interno do servidor."})
            except Exception:
                pass

    def _read_json(s):
        """Lê o corpo JSON. Devolve (dict, None) ou (None, (código, mensagem))."""
        try:
            n = int(s.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return None, (400, "Content-Length inválido.")
        if n < 0:
            return None, (400, "Content-Length inválido.")
        if n > MAX_BODY:
            return None, (413, "Pedido demasiado grande.")
        try:
            d = json.loads(s.rfile.read(n) or b"{}")
        except (ValueError, UnicodeDecodeError):
            return None, (400, "JSON inválido")
        if not isinstance(d, dict):
            return None, (400, "JSON inválido")
        return d, None

    def _do_post(s):
        global CFG, CLIENTS
        if not s.allowed():
            return s.send(403, {"error": "forbidden"})
        d, err = s._read_json()
        if err:
            return s.send(err[0], {"error": err[1]})
        results = {}
        if s.path == "/api/post":
            text = (d.get("text") or "").strip()
            ref = d.get("reply")  # {"network": ..., "ref": {...}}
            if ref is not None and not (isinstance(ref, dict) and isinstance(ref.get("ref"), dict)
                                        and isinstance(ref.get("network"), str)):
                return s.send(400, {"error": "Resposta inválida."})
            spoiler = (d.get("spoiler") or "").strip() or None
            poll = d.get("poll")
            if poll is not None and not isinstance(poll, dict):
                return s.send(400, {"error": "Sondagem inválida."})
            targets = [ref["network"]] if ref else d.get("targets", [])
            if (not isinstance(targets, list) or not targets
                    or not all(isinstance(t, str) for t in targets)):
                return s.send(400, {"error": "Escolhe pelo menos uma rede."})
            unknown = [t for t in targets if t not in CLIENTS]
            if unknown:
                return s.send(400, {"error": "Rede não configurada: " + ", ".join(unknown)})
            raw_images = d.get("images") or []
            if not isinstance(raw_images, list):
                return s.send(400, {"error": "Imagens inválidas."})
            parsed_images = []
            for img in raw_images:
                if not isinstance(img, dict):
                    return s.send(400, {"error": "Imagens inválidas."})
                raw_data = img.get("data", "")
                if not isinstance(raw_data, str):
                    return s.send(400, {"error": "Imagens inválidas."})
                if "," in raw_data:
                    hdr, b64 = raw_data.split(",", 1)
                    mime = hdr.split(";")[0].replace("data:", "") or "image/jpeg"
                else:
                    mime = img.get("mime") or "image/jpeg"
                    b64 = raw_data
                try:
                    img_bytes = base64.b64decode(b64, validate=True)
                except (binascii.Error, ValueError):
                    return s.send(400, {"error": "Imagem com codificação inválida."})
                parsed_images.append({
                    "bytes": img_bytes,
                    "mime": mime,
                    "alt": img.get("alt", ""),
                    "aspectRatio": img.get("aspectRatio")
                })
            for t in targets:
                try:
                    CLIENTS[t].post(text, ref["ref"] if ref else None, parsed_images, spoiler=spoiler, poll=poll)
                    results[t] = "ok"
                except Exception as e:
                    results[t] = str(e)
            return s.send(200, results)
        if s.path == "/api/thread":
            try:
                return s.send(200, CLIENTS[d["network"]].thread(d["ref"]))
            except Exception as e:
                return s.send(200, {"error": str(e)})
        if s.path == "/api/action":
            try:
                CLIENTS[d["network"]].act(d["action"], d["ref"])
                return s.send(200, {"ok": True})
            except Exception as e:
                return s.send(200, {"ok": False, "error": str(e)})
        if s.path == "/api/setup":
            new_cfg = dict(CFG)
            new_cfg["port"] = PORT
            if isinstance(d.get("bluesky"), dict):
                b = d["bluesky"]
                h = (b.get("handle") or "").strip().lstrip("@")
                p = (b.get("app_password") or "").strip()
                if h and p:
                    new_cfg["bluesky"] = {"handle": h, "app_password": p}
                    if b.get("service"):
                        new_cfg["bluesky"]["service"] = b["service"].strip()
                elif not h and not p and "bluesky" in new_cfg:
                    new_cfg.pop("bluesky", None)

            if isinstance(d.get("mastodon"), dict):
                m = d["mastodon"]
                inst = (m.get("instance") or "").strip().rstrip("/")
                tok = (m.get("token") or "").strip()
                if inst and tok:
                    if not inst.startswith(("http://", "https://")):
                        inst = "https://" + inst
                    new_cfg["mastodon"] = {"instance": inst, "token": tok}
                elif not inst and not tok and "mastodon" in new_cfg:
                    new_cfg.pop("mastodon", None)

            test_clients = init_clients(new_cfg)
            if not test_clients:
                return s.send(400, {"error": "Introduz dados de acesso válidos para pelo menos uma das redes."})

            try:
                write_config(new_cfg)
                CFG = new_cfg
                CLIENTS = test_clients
                return s.send(200, {"ok": True, "networks": list(CLIENTS)})
            except Exception as e:
                return s.send(500, {"error": f"Não foi possível guardar config.json: {e}"})
        s.send(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"A correr em http://127.0.0.1:{PORT}  (Ctrl+C para parar)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
