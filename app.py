#!/usr/bin/env python3
"""MastoSky: cliente local-first Bluesky + Mastodon (127.0.0.1)."""
import argparse, base64, binascii, html, ipaddress, json, os, re, socket, stat, sys, threading, time, urllib.error, urllib.parse, urllib.request, uuid, webbrowser
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


def http(method, url, data=None, token=None, headers=None, timeout=30):
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", "MastoSky/1.0")
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
            with urllib.request.urlopen(req, body, timeout=timeout) as r:
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


def byte_span(text, start, end):
    b = len(text[:start].encode("utf-8"))
    return b, b + len(text[start:end].encode("utf-8"))


_HANDLE_RE = re.compile(r"(?<![\w/@])@([a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?)+)")
_HASHTAG_RE = re.compile(r"(?<![\w&])#(\w*[^\W\d]\w*)")
_URL_RE = re.compile(r"https?://[^\s]+")


def linkify(text):
    if not text:
        return ""
    parts = []
    last = 0
    for m in re.finditer(r"https?://[^\s<]+", text):
        parts.append(html.escape(text[last:m.start()]))
        full = m.group(0)
        u = full.rstrip(".,;:!?)")
        tail = full[len(u):]
        su = safe_url(u)
        if su:
            parts.append(f'<a href="{html.escape(su, True)}" target="_blank" rel="noopener noreferrer">{html.escape(u)}</a>')
        else:
            parts.append(html.escape(u))
        parts.append(html.escape(tail))
        last = m.end()
    parts.append(html.escape(text[last:]))
    return "".join(parts).replace("\n", "<br>")


def render_bsky_text(text, facets=None):
    if not text:
        return ""
    if not facets or not isinstance(facets, list):
        return linkify(text)

    raw_bytes = text.encode("utf-8")
    valid_facets = []
    for f in facets:
        if not isinstance(f, dict):
            continue
        idx = f.get("index")
        if not isinstance(idx, dict):
            continue
        try:
            start = int(idx.get("byteStart"))
            end = int(idx.get("byteEnd"))
        except (TypeError, ValueError):
            continue
        if 0 <= start < end <= len(raw_bytes) and f.get("features"):
            valid_facets.append((start, end, f["features"]))

    if not valid_facets:
        return linkify(text)

    valid_facets.sort(key=lambda x: (x[0], -x[1]))

    out = []
    last_end = 0
    for start, end, features in valid_facets:
        if start < last_end:
            continue
        if start > last_end:
            chunk = raw_bytes[last_end:start].decode("utf-8", errors="replace")
            out.append(linkify(chunk))
        facet_chunk = raw_bytes[start:end].decode("utf-8", errors="replace")
        feat = features[0] if isinstance(features, list) and features else {}
        ftype = feat.get("$type") if isinstance(feat, dict) else ""
        if ftype == "app.bsky.richtext.facet#link":
            u = safe_url(feat.get("uri"))
            if u:
                out.append(f'<a href="{html.escape(u, True)}" target="_blank" rel="noopener noreferrer">{html.escape(facet_chunk)}</a>')
            else:
                out.append(html.escape(facet_chunk))
        elif ftype == "app.bsky.richtext.facet#mention":
            did = feat.get("did")
            if did and isinstance(did, str):
                u = safe_url(f"https://bsky.app/profile/{urllib.parse.quote(did)}")
                if u:
                    out.append(f'<a href="{html.escape(u, True)}" target="_blank" rel="noopener noreferrer">{html.escape(facet_chunk)}</a>')
                else:
                    out.append(html.escape(facet_chunk))
            else:
                out.append(html.escape(facet_chunk))
        elif ftype == "app.bsky.richtext.facet#tag":
            tag = feat.get("tag")
            if tag and isinstance(tag, str):
                u = safe_url(f"https://bsky.app/hashtag/{urllib.parse.quote(tag)}")
                if u:
                    out.append(f'<a href="{html.escape(u, True)}" target="_blank" rel="noopener noreferrer">{html.escape(facet_chunk)}</a>')
                else:
                    out.append(html.escape(facet_chunk))
            else:
                out.append(html.escape(facet_chunk))
        else:
            out.append(html.escape(facet_chunk))
        last_end = end

    if last_end < len(raw_bytes):
        chunk = raw_bytes[last_end:].decode("utf-8", errors="replace")
        out.append(linkify(chunk))

    return "".join(out)


class Clean(HTMLParser):
    """Limpa o HTML que vem do Mastodon: só fica texto, <br> e links http(s)."""
    def __init__(self, strip_quote_inline=False):
        super().__init__()
        self.o, self.sp, self.hide = [], [], 0
        self.strip_quote_inline = strip_quote_inline
        self.qi_stack = []  # tags abertas dentro de um bloco quote-inline (o primeiro é a raiz)

    _VOID = frozenset(("br", "img", "hr", "input", "meta", "link", "wbr"))

    def handle_startendtag(self, t, a):
        # <br/> & afins não abrem nada: não pode haver fecho correspondente.
        if self.qi_stack:
            return
        if t == "br":
            self.o.append("<br>")
            return
        self.handle_starttag(t, a)
        self.handle_endtag(t)

    def handle_starttag(self, t, a):
        a = dict(a)
        if self.qi_stack:
            if t not in self._VOID:
                self.qi_stack.append(t)
            return
        if self.strip_quote_inline and ("quote-inline" in (a.get("class") or "")):
            self.qi_stack.append(t)
            self.hide += 1
            return
        if t == "p" and self.o:
            self.o.append("<br><br>")
        elif t == "br":
            self.o.append("<br>")
        elif t == "span":
            self.sp.append("invisible" in (a.get("class") or ""))
            self.hide += self.sp[-1]
        elif t == "a":
            h = a.get("href") or ""
            ok = h.startswith(("http://", "https://"))
            self.o.append(f'<a href="{html.escape(h, True)}" target="_blank" rel="noopener noreferrer">' if ok else "<a>")

    def handle_endtag(self, t):
        if self.qi_stack:
            # só fecha se a tag foi realmente aberta dentro do bloco
            if t in self.qi_stack:
                while self.qi_stack and self.qi_stack.pop() != t:
                    pass
                if not self.qi_stack:
                    self.hide -= 1
            return
        if t == "a":
            self.o.append("</a>")
        elif t == "span" and self.sp:
            self.hide -= self.sp.pop()

    def handle_data(self, d):
        if not self.hide:
            self.o.append(html.escape(d))


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


def proxy_fetch_image(url_str):
    """Descarrega com segurança uma imagem remota para o gerador de cartões da publicação cruzada."""
    u = safe_url(url_str)
    if not u:
        raise ValueError("URL inválida.")
    p = urllib.parse.urlparse(u)
    host = (p.hostname or "").lower()
    if not host:
        raise ValueError("Host inválido.")
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".local"):
        raise ValueError("Acesso a endereços locais não permitido.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip and (ip.is_private or ip.is_loopback or ip.is_link_local):
        raise ValueError("Acesso a endereços de rede privada não permitido.")

    req = urllib.request.Request(
        u,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
        }
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        ctype = resp.headers.get_content_type()
        if not ctype or not (ctype.startswith("image/") or ctype == "application/octet-stream"):
            raise ValueError("O conteúdo remoto não é uma imagem válida.")
        data = resp.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("Imagem excede o limite máximo de 10MB.")
        return data, ctype if ctype.startswith("image/") else "image/jpeg"


def extract_bsky_embed(embed, did=None):
    media, quote = _extract_bsky_embed(embed, did=did)
    return safe_media_list(media), quote


def _extract_bsky_embed(embed, did=None):
    media = []
    quote = None
    if not embed:
        return media, quote
    etype = embed.get("$type", "")

    if etype in ("app.bsky.embed.images#view", "app.bsky.embed.images"):
        for i in embed.get("images", []):
            u = i.get("fullsize") or i.get("thumb") or (i.get("url") if isinstance(i.get("url"), str) else None)
            t = i.get("thumb") or i.get("fullsize") or u
            if not u and not t:
                img_obj = i.get("image")
                cid = None
                if isinstance(img_obj, dict):
                    ref = img_obj.get("ref")
                    if isinstance(ref, dict):
                        cid = ref.get("$link")
                    elif isinstance(ref, str):
                        cid = ref
                    if not cid and img_obj.get("cid"):
                        cid = img_obj.get("cid")
                elif isinstance(i.get("cid"), str):
                    cid = i.get("cid")
                if cid and did:
                    u = f"https://cdn.bsky.app/img/feed_fullsize/plain/{did}/{cid}@jpeg"
                    t = f"https://cdn.bsky.app/img/feed_thumbnail/plain/{did}/{cid}@jpeg"
            if u or t:
                media.append({
                    "type": "image",
                    "url": u,
                    "thumb": t,
                    "alt": i.get("alt", "")
                })
    elif etype in ("app.bsky.embed.video#view", "app.bsky.embed.video"):
        url = embed.get("playlist") or (embed.get("url") if isinstance(embed.get("url"), str) else None)
        thumb = embed.get("thumbnail") or (embed.get("thumb") if isinstance(embed.get("thumb"), str) else None)
        if not url:
            v_obj = embed.get("video")
            cid = None
            if isinstance(v_obj, dict):
                ref = v_obj.get("ref")
                cid = ref.get("$link") if isinstance(ref, dict) else (ref if isinstance(ref, str) else None)
            if cid and did:
                url = f"https://video.bsky.app/watch/{did}/{cid}/playlist.m3u8"
                if not thumb:
                    thumb = f"https://video.bsky.app/watch/{did}/{cid}/thumbnail.jpg"
        media.append({
            "type": "video",
            "url": url,
            "thumb": thumb,
            "alt": embed.get("alt", "")
        })
    elif etype in ("app.bsky.embed.external#view", "app.bsky.embed.external"):
        ext = embed.get("external") or {}
        thumb = ext.get("thumb")
        thumb_url = thumb if isinstance(thumb, str) else None
        if not thumb_url and isinstance(thumb, dict):
            ref = thumb.get("ref")
            cid = ref.get("$link") if isinstance(ref, dict) else (ref if isinstance(ref, str) else None)
            if cid and did:
                thumb_url = f"https://cdn.bsky.app/img/feed_thumbnail/plain/{did}/{cid}@jpeg"
        if thumb_url or ext.get("uri"):
            media.append({
                "type": "external",
                "url": ext.get("uri"),
                "thumb": thumb_url,
                "title": ext.get("title", ""),
                "description": ext.get("description", "")
            })
    elif etype in ("app.bsky.embed.recordWithMedia#view", "app.bsky.embed.recordWithMedia"):
        m_list, _ = extract_bsky_embed(embed.get("media"), did=did)
        media.extend(m_list)
        rec_obj = embed.get("record")
        quote = parse_bsky_quote(rec_obj)
    elif etype in ("app.bsky.embed.record#view", "app.bsky.embed.record"):
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
    q_did = author.get("did")
    for emb in emb_list:
        m_list, _ = extract_bsky_embed(emb, did=q_did)
        q_media.extend(m_list)
    text = val.get("text") or rec.get("text", "")
    facets = val.get("facets") or rec.get("facets")
    return {
        "network": "bluesky",
        "name": author.get("displayName") or handle,
        "handle": "@" + handle if handle else "",
        "avatar": safe_url(author.get("avatar")),
        "text": text,
        "html": render_bsky_text(text, facets) if text else "",
        "time": val.get("createdAt") or rec.get("createdAt") or rec.get("indexedAt"),
        "url": f"https://bsky.app/profile/{handle}/post/{rec.get('uri', '').split('/')[-1]}" if handle else None,
        "media": q_media
    }


def render_custom_emojis(raw_html, emojis):
    if not raw_html or not emojis or not isinstance(emojis, list):
        return raw_html
    for em in emojis:
        if not isinstance(em, dict):
            continue
        code = em.get("shortcode")
        if not code or not isinstance(code, str):
            continue
        u = safe_url(em.get("static_url") or em.get("url"))
        if not u:
            continue
        escaped_code = html.escape(code)
        img = f'<img class="emoji" src="{html.escape(u, True)}" alt=":{escaped_code}:" title=":{escaped_code}:">'
        raw_html = re.sub(rf":{re.escape(code)}:", img, raw_html)
    return raw_html


def strip_re_prefix(html_str):
    if not html_str:
        return html_str
    html_str = re.sub(r"^\s*RE:\s*<a\b[^>]*>.*?</a>(\s*<br\s*/?>\s*)*", "", html_str, flags=re.I)
    html_str = re.sub(r"(\s*<br\s*/?>\s*)*\s*RE:\s*<a\b[^>]*>.*?</a>\s*$", "", html_str, flags=re.I).strip()
    return html_str


def extract_masto_media(st, allow_card=True):
    media = []
    for m in st.get("media_attachments", []):
        mtype = m.get("type")
        if mtype in ("image", "video", "gifv"):
            media.append({
                "type": mtype,
                "url": m.get("url") or m.get("preview_url"),
                "thumb": m.get("preview_url") or m.get("url"),
                "alt": m.get("description") or ""
            })
    if not media and allow_card and st.get("card") and st["card"].get("url"):
        card = st["card"]
        media.append({
            "type": "external",
            "url": card.get("url"),
            "thumb": card.get("image"),
            "title": card.get("title", ""),
            "description": card.get("description", "")
        })
    return media


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
    q_media = extract_masto_media(qs, allow_card=True)

    cw = f"<strong>{html.escape(qs['spoiler_text'])}</strong><br>" if qs.get("spoiler_text") else ""
    q_html = strip_re_prefix(cw + clean(qs.get("content"), strip_quote_inline=True))
    q_html = render_custom_emojis(q_html, qs.get("emojis"))
    q_name = q_acc.get("display_name") or q_acc.get("username", "")
    q_name_html = render_custom_emojis(html.escape(q_name), q_acc.get("emojis")) if q_acc.get("emojis") else None

    plain_text = ((f"[{qs['spoiler_text']}] " if qs.get("spoiler_text") else "") + plain(qs.get("content"))).strip()
    out = {
        "network": "mastodon",
        "name": q_name,
        "handle": "@" + q_acc.get("acct", ""),
        "avatar": safe_url(q_acc.get("avatar")),
        "text": plain_text,
        "html": q_html,
        "time": qs.get("created_at"),
        "url": safe_url(qs.get("url")),
        "media": safe_media_list(q_media)
    }
    if q_name_html:
        out["name_html"] = q_name_html
    return out


class Bsky:
    name = "bluesky"

    def __init__(self, c):
        self.c, self.jwt, self.refresh_jwt, self.did = c, None, None, None
        self.host = c.get("service", "https://bsky.social")
        self.lock = threading.RLock()  # protege login/refresh em pedidos concorrentes
        self._handle_cache = {}

    def resolve_handle(self, handle):
        handle = (handle or "").strip().lstrip("@")
        if not handle:
            return None
        with self.lock:
            if handle in self._handle_cache:
                return self._handle_cache[handle]
        try:
            res = self.call("GET", "com.atproto.identity.resolveHandle", params={"handle": handle})
            did = res.get("did")
            if did:
                with self.lock:
                    self._handle_cache[handle] = did
                return did
        except Exception:
            pass
        return None

    def login(self):
        with self.lock:
            r = http("POST", self.host + "/xrpc/com.atproto.server.createSession",
                     {"identifier": self.c["handle"], "password": self.c["app_password"]})
            self.jwt, self.refresh_jwt, self.did = r["accessJwt"], r.get("refreshJwt"), r["did"]

    def _ensure(self):
        with self.lock:
            if not self.jwt:
                self.login()

    def _renew(self, failed_jwt):
        """Renova a sessão: primeiro refreshSession; só se falhar volta a createSession."""
        with self.lock:
            if self.jwt != failed_jwt:  # outro pedido já renovou entretanto
                return
            if self.refresh_jwt:
                try:
                    r = http("POST", self.host + "/xrpc/com.atproto.server.refreshSession", token=self.refresh_jwt)
                    self.jwt, self.refresh_jwt = r["accessJwt"], r.get("refreshJwt") or self.refresh_jwt
                    self.did = r.get("did") or self.did
                    return
                except (RuntimeError, KeyError):
                    pass
            self.jwt = None
            self.login()

    @staticmethod
    def _expired(e):
        return "ExpiredToken" in str(e) or str(e).startswith("401")

    def _authed(self, fn):
        """Executa fn(jwt); se o token expirou, renova a sessão e repete uma vez."""
        self._ensure()
        jwt = self.jwt
        try:
            return fn(jwt)
        except RuntimeError as e:
            if not self._expired(e):
                raise
            self._renew(jwt)
            return fn(self.jwt)

    def call(self, method, nsid, data=None, params=None):
        url = f"{self.host}/xrpc/{nsid}" + ("?" + urllib.parse.urlencode(params) if params else "")
        return self._authed(lambda jwt: http(method, url, data, jwt))

    def item(self, p, reason=None, reply=None):
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
            m_list, q_obj = extract_bsky_embed(emb, did=a.get("did"))
            media.extend(m_list)
            if q_obj and not quote:
                quote = q_obj
        if not media and rec.get("embed"):
            m_list, q_obj = extract_bsky_embed(rec.get("embed"), did=a.get("did"))
            media.extend(m_list)
            if q_obj and not quote:
                quote = q_obj
        dedup_media, seen_keys = [], set()
        for m in media:
            u = m.get("url") or m.get("thumb") or ""
            key = u.split("/plain/")[-1].split("@")[0] if "/plain/" in u else u
            if key and key not in seen_keys:
                seen_keys.add(key)
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
        viewer = p.get("viewer") or {}
        like_uri = viewer.get("like")
        repost_uri = viewer.get("repost")
        ref_obj = {"uri": p["uri"], "cid": p["cid"], "root": {"uri": root["uri"], "cid": root["cid"]}}
        if like_uri:
            ref_obj["like_uri"] = like_uri
        if repost_uri:
            ref_obj["repost_uri"] = repost_uri
        return {
            "network": "bluesky", "name": a.get("displayName") or a["handle"], "handle": "@" + a["handle"],
            "author_id": a.get("did") or a["handle"], "author_handle": a["handle"],
            "avatar": safe_url(a.get("avatar")), "text": rec.get("text", ""),
            "html": render_bsky_text(rec.get("text", ""), rec.get("facets")),
            "time": reason.get("indexedAt") or p.get("indexedAt") or rec["createdAt"],
            "boosted_by": by.get("displayName") or by.get("handle"), "reply_to": rt,
            "media": media,
            "quote": quote,
            "replies": p.get("replyCount", 0), "boosts": p.get("repostCount", 0), "likes": p.get("likeCount", 0),
            "liked": bool(like_uri), "boosted": bool(repost_uri),
            "is_own": bool(self.did and a.get("did") == self.did),
            "url": f"https://bsky.app/profile/{a['handle']}/post/{p['uri'].split('/')[-1]}",
            "ref": ref_obj,
            "is_reply": bool(rec.get("reply")),
        }

    def timeline(self, cursor=None):
        params = {"limit": 40}
        if cursor:
            params["cursor"] = cursor
        r = self.call("GET", "app.bsky.feed.getTimeline", params=params)
        feed = r.get("feed", [])
        return [self.item(it["post"], it.get("reason"), it.get("reply")) for it in feed], r.get("cursor")

    def explore(self, cursor=None):
        feed_uri = "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/whats-hot"
        params = {"feed": feed_uri, "limit": 40}
        if cursor:
            params["cursor"] = cursor
        r = self.call("GET", "app.bsky.feed.getFeed", params=params)
        feed = r.get("feed", [])
        return [self.item(it["post"], it.get("reason"), it.get("reply")) for it in feed], r.get("cursor")

    def thread(self, ref):
        ok = "app.bsky.feed.defs#threadViewPost"
        r = self.call("GET", "app.bsky.feed.getPostThread",
                   params={"uri": ref["uri"], "depth": 8, "parentHeight": 30})["thread"]
        if r.get("$type") != ok:
            raise RuntimeError("Post não disponível (apagado ou bloqueado).")
        ancestors, n = [], r.get("parent")
        while n and n.get("$type") == ok:
            ancestors.insert(0, self.item(n["post"]))
            n = n.get("parent")

        def tree(node):
            out = []
            for c in node.get("replies") or []:
                if c.get("$type") == ok:
                    i = self.item(c["post"])
                    i["children"] = tree(c)
                    out.append(i)
            return out
        return {"ancestors": ancestors, "focus": self.item(r["post"]), "replies": tree(r)}

    def user_profile(self, actor):
        self._ensure()
        p = self.call("GET", "app.bsky.actor.getProfile", params={"actor": actor})
        desc = p.get("description") or ""
        bio_html = render_bsky_text(desc) if desc else ""
        return {
            "network": "bluesky",
            "name": p.get("displayName") or p.get("handle") or "",
            "handle": "@" + (p.get("handle") or ""),
            "avatar": safe_url(p.get("avatar")),
            "banner": safe_url(p.get("banner")),
            "bio": bio_html,
            "followers": p.get("followersCount", 0),
            "following": p.get("followsCount", 0),
            "posts_count": p.get("postsCount", 0),
            "url": f"https://bsky.app/profile/{p.get('handle')}"
        }

    def user_feed(self, actor, cursor=None):
        self._ensure()
        params = {"actor": actor, "limit": 40}
        if cursor:
            params["cursor"] = cursor
        r = self.call("GET", "app.bsky.feed.getAuthorFeed", params=params)
        feed = r.get("feed", [])
        return [self.item(it["post"], it.get("reason"), it.get("reply")) for it in feed], r.get("cursor")

    def profile(self):
        self._ensure()
        return self.user_profile(self.did)

    def author_feed(self, cursor=None):
        self._ensure()
        return self.user_feed(self.did, cursor=cursor)

    def upload_blob(self, raw_bytes, mime="image/jpeg"):
        url = f"{self.host}/xrpc/com.atproto.repo.uploadBlob"
        r = self._authed(lambda jwt: http("POST", url, data=raw_bytes, token=jwt, headers={"Content-Type": mime}))
        return r["blob"]

    def post(self, text, ref=None, images=None, spoiler=None, poll=None, lang=None, quote=None):
        self._ensure()
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
        for m in _URL_RE.finditer(final_text):
            url = m.group().rstrip(".,;:!?)")
            b_start, b_end = byte_span(final_text, m.start(), m.start() + len(url))
            facets.append({"index": {"byteStart": b_start, "byteEnd": b_end},
                           "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]})
        for m in _HANDLE_RE.finditer(final_text):
            handle = m.group(1)
            did = self.resolve_handle(handle)
            if did:
                b_start, b_end = byte_span(final_text, m.start(), m.end())
                facets.append({"index": {"byteStart": b_start, "byteEnd": b_end},
                               "features": [{"$type": "app.bsky.richtext.facet#mention", "did": did}]})
        for m in _HASHTAG_RE.finditer(final_text):
            tag = m.group(1)
            b_start, b_end = byte_span(final_text, m.start(), m.end())
            facets.append({"index": {"byteStart": b_start, "byteEnd": b_end},
                           "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag}]})
        clean_facets = []
        last_end = 0
        for f in sorted(facets, key=lambda f: (f["index"]["byteStart"], -f["index"]["byteEnd"])):
            st, en = f["index"]["byteStart"], f["index"]["byteEnd"]
            if st >= last_end and en > st:
                clean_facets.append(f)
                last_end = en
        rec = {"$type": "app.bsky.feed.post", "text": final_text, "createdAt": now_iso()}
        if clean_facets:
            rec["facets"] = clean_facets
        if lang:
            rec["langs"] = [lang]
        if ref:
            rec["reply"] = {"root": ref["root"], "parent": {"uri": ref["uri"], "cid": ref["cid"]}}
        
        embed_imgs = []
        if images:
            for img in images:
                blob = self.upload_blob(img["bytes"], img.get("mime", "image/jpeg"))
                item = {"alt": img.get("alt", "") or "", "image": blob}
                if img.get("aspectRatio"):
                    item["aspectRatio"] = img["aspectRatio"]
                embed_imgs.append(item)

        if quote and quote.get("network") == "bluesky" and quote.get("ref", {}).get("uri"):
            q_record = {
                "$type": "app.bsky.embed.record",
                "record": {"uri": quote["ref"]["uri"], "cid": quote["ref"]["cid"]}
            }
            if embed_imgs:
                rec["embed"] = {
                    "$type": "app.bsky.embed.recordWithMedia",
                    "record": q_record,
                    "media": {"$type": "app.bsky.embed.images", "images": embed_imgs}
                }
            else:
                rec["embed"] = q_record
        elif quote and quote.get("network") == "mastodon":
            if not embed_imgs and quote.get("url"):
                title = quote.get("name") or "Publicação no Mastodon"
                if quote.get("handle"):
                    title += f" ({quote['handle']})"
                rec["embed"] = {
                    "$type": "app.bsky.embed.external",
                    "external": {
                        "uri": quote["url"],
                        "title": title,
                        "description": (quote.get("text") or "")[:300]
                    }
                }
            elif embed_imgs:
                rec["embed"] = {"$type": "app.bsky.embed.images", "images": embed_imgs}
                if quote.get("url") and quote["url"] not in rec["text"]:
                    rec["text"] = (rec["text"] + "\n\n" + quote["url"]).strip()
        elif embed_imgs:
            rec["embed"] = {"$type": "app.bsky.embed.images", "images": embed_imgs}

        self.call("POST", "com.atproto.repo.createRecord",
               {"repo": self.did, "collection": "app.bsky.feed.post", "record": rec})

    def act(self, action, ref):
        self._ensure()
        if action in ("like", "boost"):
            col = {"like": "app.bsky.feed.like", "boost": "app.bsky.feed.repost"}[action]
            return self.call("POST", "com.atproto.repo.createRecord", {
                "repo": self.did, "collection": col,
                "record": {"$type": col, "subject": {"uri": ref["uri"], "cid": ref["cid"]}, "createdAt": now_iso()}})
        elif action in ("unlike", "unboost"):
            col = {"unlike": "app.bsky.feed.like", "unboost": "app.bsky.feed.repost"}[action]
            target_uri = ref.get("like_uri" if action == "unlike" else "repost_uri") or ref.get("uri")
            if not target_uri:
                raise ApiError("URI do registo a remover não fornecido.")
            rkey = target_uri.split("/")[-1]
            return self.call("POST", "com.atproto.repo.deleteRecord", {
                "repo": self.did, "collection": col, "rkey": rkey})
        elif action == "delete":
            target_uri = ref.get("uri")
            if not target_uri:
                raise ApiError("URI do post a remover não fornecido.")
            rkey = target_uri.split("/")[-1]
            return self.call("POST", "com.atproto.repo.deleteRecord", {
                "repo": self.did, "collection": "app.bsky.feed.post", "rkey": rkey})
        else:
            raise ApiError(f"Ação desconhecida: {action}")

    def notifications(self, cursor=None):
        kinds = {"like": "like", "like-via-repost": "like_repost", "repost": "boost", "repost-via-repost": "boost_repost",
                 "follow": "follow", "mention": "mention", "reply": "reply", "quote": "quote"}
        params = {"limit": 40}
        if cursor:
            params["cursor"] = cursor
        r = self.call("GET", "app.bsky.notification.listNotifications", params=params)
        ns = r.get("notifications", [])
        next_cursor = r.get("cursor")

        def get_subj_uri(notif):
            # Priorizar URI de post (app.bsky.feed.post).
            # Em likes/reposts de republicações do utilizador, `reasonSubject` aponta para
            # `app.bsky.feed.repost`, enquanto `record.subject.uri` aponta para o post original.
            rec = notif.get("record")
            if isinstance(rec, dict):
                s = rec.get("subject")
                s_uri = s.get("uri") if isinstance(s, dict) else (s if isinstance(s, str) else None)
                if s_uri and "/app.bsky.feed.post/" in s_uri:
                    return s_uri
            rs = notif.get("reasonSubject")
            if rs and "/app.bsky.feed.post/" in rs:
                return rs
            if isinstance(rec, dict):
                s = rec.get("subject")
                s_uri = s.get("uri") if isinstance(s, dict) else (s if isinstance(s, str) else None)
                if s_uri:
                    return s_uri
            return notif.get("reasonSubject")

        subj_set = set()
        for n in ns:
            su = get_subj_uri(n)
            if su and "/app.bsky.feed.post/" in su:
                subj_set.add(su)
            n_uri = n.get("uri")
            if n_uri and "/app.bsky.feed.post/" in n_uri:
                subj_set.add(n_uri)

        subjects = sorted(subj_set)
        posts = {}
        for i in range(0, len(subjects), 25):
            res = self.call("GET", "app.bsky.feed.getPosts", params=[("uris", u) for u in subjects[i:i + 25]])
            for p in res.get("posts", []):
                posts[p["uri"]] = p
        out = []
        for n in ns:
            reason = n.get("reason", "other")
            reason_subject = n.get("reasonSubject") or ""
            is_via_repost = "/app.bsky.feed.repost/" in reason_subject
            kind = kinds.get(reason, "other")
            if is_via_repost:
                if kind == "like":
                    kind = "like_repost"
                elif kind == "boost":
                    kind = "boost_repost"

            a = n["author"]
            subj_uri = get_subj_uri(n)
            subject = posts.get(subj_uri) if subj_uri else None
            n_post = posts.get(n.get("uri")) if n.get("uri") else None
            ref, text, facets, url = None, "", None, f"https://bsky.app/profile/{a['handle']}"
            media, quote = [], None

            if kind in ("reply", "mention", "quote"):
                rec = n.get("record") or {}
                text = rec.get("text", "")
                facets = rec.get("facets")
                root = rec.get("reply", {}).get("root") or {"uri": n["uri"], "cid": n["cid"]}
                ref = {"uri": n["uri"], "cid": n["cid"], "root": {"uri": root["uri"], "cid": root["cid"]}}
                url = f"https://bsky.app/profile/{a['handle']}/post/{n['uri'].split('/')[-1]}"
                target_did = a.get("did") or (n.get("uri").replace("at://", "").split("/")[0] if n.get("uri") else None)
                if n_post:
                    embed_sources = []
                    if n_post.get("embed"): embed_sources.append(n_post.get("embed"))
                    for emb in n_post.get("embeds") or []:
                        if emb not in embed_sources: embed_sources.append(emb)
                    for emb in embed_sources:
                        m_list, q_obj = extract_bsky_embed(emb, did=target_did)
                        media.extend(m_list)
                        if q_obj and not quote:
                            quote = q_obj
                if not media and rec.get("embed"):
                    m_list, q_obj = extract_bsky_embed(rec.get("embed"), did=target_did)
                    media.extend(m_list)
                    if q_obj and not quote:
                        quote = q_obj
            elif subject:
                srec = subject.get("record") or {}
                text = srec.get("text", "")
                facets = srec.get("facets")
                url = f"https://bsky.app/profile/{subject['author']['handle']}/post/{subject['uri'].split('/')[-1]}"
                subj_did = (subject.get("author") or {}).get("did") or (subj_uri.replace("at://", "").split("/")[0] if subj_uri else None)
                embed_sources = []
                if subject.get("embed"): embed_sources.append(subject.get("embed"))
                for emb in subject.get("embeds") or []:
                    if emb not in embed_sources: embed_sources.append(emb)

                for emb in embed_sources:
                    m_list, q_obj = extract_bsky_embed(emb, did=subj_did)
                    media.extend(m_list)
                    if q_obj and not quote:
                        quote = q_obj

                if not media:
                    rec_sources = []
                    if srec.get("embed"): rec_sources.append(srec.get("embed"))
                    for emb in srec.get("embeds") or []:
                        if emb not in rec_sources: rec_sources.append(emb)
                    for emb in rec_sources:
                        m_list, q_obj = extract_bsky_embed(emb, did=subj_did)
                        media.extend(m_list)
                        if q_obj and not quote:
                            quote = q_obj

                if not text and not media and not quote:
                    all_sources = embed_sources or [srec.get("embed")]
                    for emb in all_sources:
                        stype = emb.get("$type", "") if isinstance(emb, dict) else ""
                        if "images" in stype:
                            text = "📷 [Imagem]"
                            break
                        elif "video" in stype:
                            text = "🎬 [Vídeo]"
                            break
                        elif "record" in stype:
                            text = "💬 [Citação]"
                            break
            elif subj_uri and kind in ("like", "like_repost", "boost", "boost_repost"):
                post_id = subj_uri.split("/")[-1]
                author_part = subj_uri.replace("at://", "").split("/")[0]
                url = f"https://bsky.app/profile/{author_part}/post/{post_id}"
                text = "(Publicação indisponível)"

            if media:
                dedup_m, seen_keys = [], set()
                for m in media:
                    u = m.get("url") or m.get("thumb") or ""
                    key = u.split("/plain/")[-1].split("@")[0] if "/plain/" in u else u
                    if key and key not in seen_keys:
                        seen_keys.add(key)
                        dedup_m.append(m)
                media = dedup_m
                if text in ("📷 [Imagem]", "🎬 [Vídeo]", "💬 [Citação]"):
                    text = ""
            out.append({"network": "bluesky", "kind": kind, "name": a.get("displayName") or a["handle"],
                        "handle": "@" + a["handle"], "author_id": a.get("did") or a["handle"],
                        "author_handle": a["handle"], "avatar": safe_url(a.get("avatar")),
                        "html": render_bsky_text(text, facets) if text else "", "time": n["indexedAt"], "url": url, "ref": ref,
                        "media": safe_media_list(media), "quote": quote})
        return out, next_cursor


class Masto:
    name = "mastodon"

    def __init__(self, c):
        self.base, self.token = c["instance"].rstrip("/"), c["token"]
        self.cache = {}  # posts "pai" já obtidos
        self.cache_lock = threading.Lock()  # a cache é usada por várias threads em paralelo
        self.my_id = None

    def get_my_id(self):
        if self.my_id:
            return self.my_id
        try:
            acc = self.call("GET", "/api/v1/accounts/verify_credentials")
            self.my_id = str(acc.get("id"))
            return self.my_id
        except Exception:
            return None

    def call(self, method, path, data=None, params=None, timeout=30):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        return http(method, url, data, self.token, timeout=timeout)

    def parent(self, sid):
        with self.cache_lock:
            if sid in self.cache:
                return self.cache[sid]
        try:
            p = self.call("GET", f"/api/v1/statuses/{sid}", timeout=4)
        except Exception:
            return None
        with self.cache_lock:
            if len(self.cache) > 500:
                self.cache.clear()
            self.cache[sid] = p
        return p

    def reply_info(self, p):
        if not p:
            return {"name": None, "handle": None, "text": ""}
        a = p["account"]
        return {"name": a.get("display_name") or a["username"], "handle": "@" + a["acct"],
                "text": preview(p.get("spoiler_text") or plain(p.get("content")))}

    def item(self, st, parents=None):
        x = st.get("reblog") or st
        a = x["account"]
        rt = None
        if parents is not None and x.get("in_reply_to_id"):
            rt = self.reply_info(parents.get(x["in_reply_to_id"]))
        cw = f"<strong>{html.escape(x['spoiler_text'])}</strong><br>" if x.get("spoiler_text") else ""
        quote = parse_masto_quote(x)
        raw_html = clean(x.get("content"), strip_quote_inline=bool(quote))
        if quote:
            raw_html = strip_re_prefix(raw_html)

        media = extract_masto_media(x, allow_card=(not quote))
        my_id = self.get_my_id()
        name_plain = a.get("display_name") or a.get("username", "")
        name_html = render_custom_emojis(html.escape(name_plain), a.get("emojis")) if a.get("emojis") else None
        final_html = render_custom_emojis(cw + raw_html, x.get("emojis"))
        plain_text = ((f"[{x['spoiler_text']}] " if x.get("spoiler_text") else "") + plain(x.get("content"))).strip()
        out = {
            "network": "mastodon", "name": name_plain, "handle": "@" + a.get("acct", ""),
            "author_id": str(a.get("id")), "author_handle": a.get("acct") or a.get("username", ""),
            "avatar": safe_url(a.get("avatar")), "text": plain_text, "html": final_html,
            "time": st.get("created_at"),
            "boosted_by": (st["account"].get("display_name") or st["account"]["username"]) if st.get("reblog") else None,
            "media": safe_media_list(media),
            "quote": quote,
            "replies": x.get("replies_count", 0), "boosts": x.get("reblogs_count", 0), "likes": x.get("favourites_count", 0),
            "liked": bool(x.get("favourited")), "boosted": bool(x.get("reblogged")),
            "is_own": bool(my_id and str(a.get("id")) == my_id),
            "url": safe_url(x.get("url")), "ref": {"id": x["id"]}, "reply_to": rt,
            "is_reply": bool(x.get("in_reply_to_id")),
        }
        if name_html:
            out["name_html"] = name_html
        return out

    def _fetch_statuses(self, path, cursor=None, params=None):
        p = {"limit": 40}
        if params:
            p.update(params)
        if cursor:
            p["max_id"] = cursor
        sts = self.call("GET", path, params=p)
        parents = {x["id"]: x for x in (st.get("reblog") or st for st in sts)}
        need = list({x["in_reply_to_id"] for x in parents.values() if x.get("in_reply_to_id")} - set(parents))
        with ThreadPoolExecutor(max_workers=6) as ex:
            for sid, par in zip(need, ex.map(self.parent, need)):
                if par:
                    parents[sid] = par
        next_cursor = str(sts[-1]["id"]) if sts else None
        return [self.item(st, parents) for st in sts], next_cursor

    def timeline(self, cursor=None):
        return self._fetch_statuses("/api/v1/timelines/home", cursor=cursor)

    def explore(self, cursor=None):
        return self._fetch_statuses("/api/v1/trends/statuses", cursor=cursor)

    def _format_acc(self, acc):
        name_plain = acc.get("display_name") or acc.get("username", "")
        name_html = render_custom_emojis(html.escape(name_plain), acc.get("emojis")) if acc.get("emojis") else None
        bio_html = render_custom_emojis(clean(acc.get("note")), acc.get("emojis"))
        out = {
            "network": "mastodon",
            "id": str(acc.get("id")),
            "name": name_plain,
            "handle": "@" + (acc.get("acct") or acc.get("username") or ""),
            "avatar": safe_url(acc.get("avatar")),
            "banner": safe_url(acc.get("header")),
            "bio": bio_html,
            "followers": acc.get("followers_count", 0),
            "following": acc.get("following_count", 0),
            "posts_count": acc.get("statuses_count", 0),
            "url": safe_url(acc.get("url"))
        }
        if name_html:
            out["name_html"] = name_html
        return out

    def profile(self):
        acc = self.call("GET", "/api/v1/accounts/verify_credentials")
        self.my_id = str(acc.get("id"))
        return self._format_acc(acc)

    def user_profile(self, actor):
        actor_str = str(actor).strip().lstrip("@")
        if actor_str.isdigit():
            acc = self.call("GET", f"/api/v1/accounts/{actor_str}")
        else:
            acc = self.call("GET", "/api/v1/accounts/lookup", params={"acct": actor_str})
        return self._format_acc(acc)

    def user_feed(self, actor, cursor=None):
        actor_str = str(actor).strip().lstrip("@")
        if not actor_str.isdigit():
            prof = self.user_profile(actor_str)
            acc_id = prof.get("id")
        else:
            acc_id = actor_str
        return self._fetch_statuses(f"/api/v1/accounts/{acc_id}/statuses", cursor=cursor)

    def author_feed(self, cursor=None):
        my_id = self.get_my_id()
        if not my_id:
            return [], None
        return self.user_feed(my_id, cursor=cursor)

    def thread(self, ref):
        st = self.call("GET", f"/api/v1/statuses/{ref['id']}")
        c = self.call("GET", f"/api/v1/statuses/{ref['id']}/context")
        nodes = {}
        for d in c["descendants"]:
            i = self.item(d)
            i["children"] = []
            nodes[d["id"]] = i
        replies = []
        for d in c["descendants"]:
            parent = nodes.get(d.get("in_reply_to_id"))
            (parent["children"] if parent else replies).append(nodes[d["id"]])
        return {"ancestors": [self.item(x) for x in c["ancestors"]], "focus": self.item(st), "replies": replies}

    def upload_media(self, raw_bytes, mime="image/jpeg", description=""):
        ext = mime.split("/")[-1] if "/" in mime else "jpg"
        data, ctype = multipart_encode({"description": description or ""},
                                       {"file": (f"media.{ext}", raw_bytes, mime)})
        r = http("POST", self.base + "/api/v2/media", data=data, token=self.token,
                 headers={"Content-Type": ctype})
        return r["id"]

    def post(self, text, ref=None, images=None, spoiler=None, poll=None, lang=None, visibility=None, quote=None):
        media_ids = []
        if images:
            for img in images:
                mid = self.upload_media(img["bytes"], img.get("mime", "image/jpeg"), img.get("alt", ""))
                media_ids.append(mid)
        status_text = (text or "").strip()
        if quote and quote.get("url") and quote["url"] not in status_text:
            status_text = (status_text + "\n\n" + quote["url"]).strip()
        data = {"status": status_text}
        if spoiler:
            data["spoiler_text"] = spoiler
        if lang:
            data["language"] = lang
        if visibility:
            data["visibility"] = visibility
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
        self.call("POST", "/api/v1/statuses", data)

    def act(self, action, ref):
        if action == "delete":
            return self.call("DELETE", f"/api/v1/statuses/{ref['id']}")
        endpoints = {
            "like": f"/api/v1/statuses/{ref['id']}/favourite",
            "unlike": f"/api/v1/statuses/{ref['id']}/unfavourite",
            "boost": f"/api/v1/statuses/{ref['id']}/reblog",
            "unboost": f"/api/v1/statuses/{ref['id']}/unreblog",
        }
        if action not in endpoints:
            raise ApiError(f"Ação desconhecida: {action}")
        return self.call("POST", endpoints[action])

    def notifications(self, cursor=None):
        kinds = {"favourite": "like", "reblog": "boost", "follow": "follow", "follow_request": "follow_request",
                 "mention": "mention", "quote": "quote", "status": "status", "update": "update", "poll": "poll"}
        params = {"limit": 40}
        if cursor:
            params["max_id"] = cursor
        raw = self.call("GET", "/api/v1/notifications", params=params)
        next_cursor = str(raw[-1]["id"]) if raw else None
        out = []
        for n in raw:
            a, st = n["account"], n.get("status")
            kind = kinds.get(n["type"], "other")
            if kind == "mention" and st and st.get("in_reply_to_id"):
                kind = "reply"
            cw = f"<strong>{html.escape(st['spoiler_text'])}</strong><br>" if st and st.get("spoiler_text") else ""
            notif_html = render_custom_emojis(cw + clean(st.get("content")), st.get("emojis")) if st else ""
            st_media = extract_masto_media(st, allow_card=True) if st else []
            st_quote = parse_masto_quote(st) if st else None
            a_emojis = a.get("emojis")
            a_name = a.get("display_name") or a.get("username", "")
            a_name_html = render_custom_emojis(html.escape(a_name), a_emojis) if a_emojis else None
            notif_item = {
                "network": "mastodon", "kind": kind, "name": a_name,
                "handle": "@" + a.get("acct", ""), "author_id": str(a.get("id")),
                "author_handle": a.get("acct") or a.get("username", ""), "avatar": safe_url(a.get("avatar")),
                "html": notif_html, "time": n.get("created_at"),
                "url": safe_url((st or {}).get("url") or a.get("url")),
                "ref": {"id": st["id"]} if st and kind in ("reply", "mention", "quote") else None,
                "media": safe_media_list(st_media),
                "quote": st_quote
            }
            if a_name_html:
                notif_item["name_html"] = a_name_html
            out.append(notif_item)
        return out, next_cursor


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
       "img-src 'self' https: data: blob:; media-src https: blob:; connect-src 'self' https:; worker-src blob:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class H(BaseHTTPRequestHandler):
    verbose = False

    def log_message(self, *a):
        if self.verbose:
            super().log_message(*a)

    def allowed(self):
        # Protege contra outros sites a falarem com o servidor local.
        ok = (f"127.0.0.1:{PORT}", f"localhost:{PORT}")
        o = self.headers.get("Origin")
        return self.headers.get("Host") in ok and (o is None or o in [f"http://{h}" for h in ok])

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        ct_header = ctype if (ctype.startswith("image/") and ctype != "image/svg+xml") or ctype == "application/octet-stream" else (ctype + "; charset=utf-8")
        self.send_header("Content-Type", ct_header)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", CSP)
        if ctype.startswith("image/"):
            self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not self.allowed():
            return self.send(403, {"error": "forbidden"})
        if path == "/":
            return self.send(200, (DIR / "index.html").read_bytes(), "text/html")
        if path == "/vendor/hls.min.js":
            return self.send(200, (DIR / "vendor" / "hls.min.js").read_bytes(), "application/javascript")
        if path.startswith("/brand/"):
            rel = path[7:]
            target = (DIR / "brand" / rel).resolve()
            if target.is_file() and str(target).startswith(str((DIR / "brand").resolve())):
                mime = "image/svg+xml" if path.endswith(".svg") else ("text/css" if path.endswith(".css") else "application/octet-stream")
                return self.send(200, target.read_bytes(), mime)
        if path in ("/favicon.ico", "/favicon.svg"):
            fav = DIR / "brand" / "favicon.svg"
            if fav.is_file():
                return self.send(200, fav.read_bytes(), "image/svg+xml")
        if path == "/api/proxy_image":
            qs = urllib.parse.parse_qs(parsed.query)
            target_url = qs.get("url", [None])[0]
            if not target_url:
                return self.send(400, {"error": "Parâmetro url em falta."})
            try:
                data, ctype = proxy_fetch_image(target_url)
                return self.send(200, data, ctype)
            except Exception as e:
                return self.send(400, {"error": str(e)})
        if path == "/api/status":
            return self.send(200, {
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
        if path == "/api/profile":
            profiles, errors = {}, {}
            for name, client in CLIENTS.items():
                try:
                    profiles[name] = client.profile()
                except Exception as e:
                    errors[name] = str(e)
            return self.send(200, {"profiles": profiles, "errors": errors, "networks": list(CLIENTS)})
        if path == "/api/user_profile":
            qs = urllib.parse.parse_qs(parsed.query)
            net = qs.get("network", [None])[0]
            actor = qs.get("actor", [None])[0]
            if not net or net not in CLIENTS:
                return self.send(400, {"error": "Rede inválida ou não configurada."})
            if not actor:
                return self.send(400, {"error": "Autor em falta."})
            try:
                prof = CLIENTS[net].user_profile(actor)
                return self.send(200, {"profile": prof})
            except Exception as e:
                return self.send(500, {"error": str(e)})
        if path == "/api/user_feed":
            qs = urllib.parse.parse_qs(parsed.query)
            net = qs.get("network", [None])[0]
            actor = qs.get("actor", [None])[0]
            cursor = qs.get("cursor", [None])[0]
            if not net or net not in CLIENTS:
                return self.send(400, {"error": "Rede inválida ou não configurada."})
            if not actor:
                return self.send(400, {"error": "Autor em falta."})
            try:
                res = CLIENTS[net].user_feed(actor, cursor=cursor)
                if isinstance(res, tuple):
                    its, nxt = res
                else:
                    its, nxt = res, None
                return self.send(200, {"items": its, "cursor": nxt})
            except Exception as e:
                return self.send(500, {"error": str(e)})
        if path in ("/api/timeline", "/api/notifications", "/api/explore", "/api/profile/feed"):
            if not CLIENTS:
                return self.send(200, {"items": [], "errors": {}, "networks": [], "cursors": {}})
            what = "author_feed" if path == "/api/profile/feed" else path.rsplit("/", 1)[1]
            qs = urllib.parse.parse_qs(parsed.query)
            target_net = qs.get("network", [None])[0]
            cursors_in = {
                "bluesky": qs.get("cursor_bluesky", [None])[0],
                "mastodon": qs.get("cursor_mastodon", [None])[0]
            }
            active_clients = [c for c in CLIENTS.values() if not target_net or c.name == target_net]
            network_items, errors, next_cursors = {}, {}, {}

            def get(c):
                try:
                    c_cursor = cursors_in.get(c.name)
                    res = getattr(c, what)(cursor=c_cursor)
                    if isinstance(res, tuple):
                        its, nxt = res
                    else:
                        its, nxt = res, None
                    return c.name, its, nxt, None
                except Exception as e:
                    return c.name, [], None, str(e)
            with ThreadPoolExecutor() as ex:
                for name, its, nxt, err in ex.map(get, active_clients):
                    network_items[name] = its
                    if nxt:
                        next_cursors[name] = nxt
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
            return self.send(200, {"items": items, "errors": errors, "networks": list(CLIENTS), "cursors": next_cursors})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        try:
            self._do_post()
        except Exception:
            # Resposta genérica: nunca expor tracebacks nem segredos.
            try:
                self.send(500, {"error": "Erro interno do servidor."})
            except Exception:
                pass

    def _read_json(self):
        """Lê o corpo JSON. Devolve (dict, None) ou (None, (código, mensagem))."""
        try:
            n = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return None, (400, "Content-Length inválido.")
        if n < 0:
            return None, (400, "Content-Length inválido.")
        if n > MAX_BODY:
            return None, (413, "Pedido demasiado grande.")
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, UnicodeDecodeError):
            return None, (400, "JSON inválido")
        if not isinstance(d, dict):
            return None, (400, "JSON inválido")
        return d, None

    def _do_post(self):
        global CFG, CLIENTS
        if not self.allowed():
            return self.send(403, {"error": "forbidden"})
        d, err = self._read_json()
        if err:
            return self.send(err[0], {"error": err[1]})
        results = {}
        if self.path == "/api/post":
            text = (d.get("text") or "").strip()
            ref = d.get("reply")  # {"network": ..., "ref": {...}}
            if ref is not None and not (isinstance(ref, dict) and isinstance(ref.get("ref"), dict)
                                        and isinstance(ref.get("network"), str)):
                return self.send(400, {"error": "Resposta inválida."})
            spoiler = (d.get("spoiler") or "").strip() or None
            poll = d.get("poll")
            if poll is not None and not isinstance(poll, dict):
                return self.send(400, {"error": "Sondagem inválida."})
            lang = d.get("lang")
            if lang is None:
                lang = CFG.get("default_lang")
            if lang is not None:
                if not isinstance(lang, str):
                    return self.send(400, {"error": "Idioma inválido."})
                lang = lang.strip().lower()
                if not lang or not re.match(r"^[a-z]{2}(-[a-z]{2})?$", lang):
                    return self.send(400, {"error": "Idioma inválido."})
            visibility = d.get("visibility")
            if visibility is not None:
                if not isinstance(visibility, str) or visibility not in ("public", "unlisted", "private", "direct"):
                    return self.send(400, {"error": "Visibilidade inválida."})
            quote = d.get("quote")
            if quote is not None and not isinstance(quote, dict):
                return self.send(400, {"error": "Citação inválida."})
            targets = [ref["network"]] if ref else d.get("targets", [])
            if (not isinstance(targets, list) or not targets
                    or not all(isinstance(t, str) for t in targets)):
                return self.send(400, {"error": "Escolhe pelo menos uma rede."})
            unknown = [t for t in targets if t not in CLIENTS]
            if unknown:
                return self.send(400, {"error": "Rede não configurada: " + ", ".join(unknown)})
            raw_images = d.get("images") or []
            if not isinstance(raw_images, list):
                return self.send(400, {"error": "Imagens inválidas."})
            parsed_images = []
            for img in raw_images:
                if not isinstance(img, dict):
                    return self.send(400, {"error": "Imagens inválidas."})
                raw_data = img.get("data", "")
                if not isinstance(raw_data, str):
                    return self.send(400, {"error": "Imagens inválidas."})
                if "," in raw_data:
                    hdr, b64 = raw_data.split(",", 1)
                    mime = hdr.split(";")[0].replace("data:", "") or "image/jpeg"
                else:
                    mime = img.get("mime") or "image/jpeg"
                    b64 = raw_data
                try:
                    img_bytes = base64.b64decode(b64, validate=True)
                except (binascii.Error, ValueError):
                    return self.send(400, {"error": "Imagem com codificação inválida."})
                parsed_images.append({
                    "bytes": img_bytes,
                    "mime": mime,
                    "alt": img.get("alt", ""),
                    "aspectRatio": img.get("aspectRatio")
                })
            for t in targets:
                try:
                    kwargs = {"spoiler": spoiler, "poll": poll, "lang": lang, "quote": quote}
                    if t == "mastodon" and visibility:
                        kwargs["visibility"] = visibility
                    CLIENTS[t].post(text, ref["ref"] if ref else None, parsed_images, **kwargs)
                    results[t] = "ok"
                except Exception as e:
                    results[t] = str(e)
            return self.send(200, results)
        if self.path == "/api/thread":
            try:
                return self.send(200, CLIENTS[d["network"]].thread(d["ref"]))
            except Exception as e:
                return self.send(200, {"error": str(e)})
        if self.path == "/api/action":
            try:
                res = CLIENTS[d["network"]].act(d["action"], d["ref"])
                out = {"ok": True}
                if isinstance(res, dict) and "uri" in res:
                    out["uri"] = res["uri"]
                return self.send(200, out)
            except Exception as e:
                return self.send(200, {"ok": False, "error": str(e)})
        if self.path == "/api/setup":
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
                return self.send(400, {"error": "Introduz dados de acesso válidos para pelo menos uma das redes."})

            try:
                write_config(new_cfg)
                CFG = new_cfg
                CLIENTS = test_clients
                return self.send(200, {"ok": True, "networks": list(CLIENTS)})
            except Exception as e:
                return self.send(500, {"error": f"Não foi possível guardar config.json: {e}"})
        self.send(404, {"error": "not found"})


def main():
    global PORT
    parser = argparse.ArgumentParser(description="MastoSky: cliente local-first Bluesky + Mastodon.")
    parser.add_argument("--port", type=int, default=None, help="Porto HTTP local (por omissão: config.json ou 8000)")
    parser.add_argument("--open", action="store_true", help="Abrir automaticamente o navegador predefinido")
    parser.add_argument("--verbose", action="store_true", help="Ativar registo de pedidos HTTP em stderr")
    args = parser.parse_args()

    if args.port:
        PORT = args.port
    if args.verbose:
        H.verbose = True

    url = f"http://127.0.0.1:{PORT}"
    server = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"MastoSky a correr em {url}  (Ctrl+C para parar)")

    if args.open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nA encerrar MastoSky...")
        server.server_close()


if __name__ == "__main__":
    main()
