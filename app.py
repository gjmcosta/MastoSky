#!/usr/bin/env python3
"""MastoSky: cliente local-first Bluesky + Mastodon (127.0.0.1)."""
import argparse, base64, binascii, hmac, html, ipaddress, json, os, re, secrets, socket, ssl, stat, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request, uuid, webbrowser, zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIR = Path(__file__).parent
_ENV_DATA_DIR = os.environ.get("MASTOSKY_DATA_DIR", "").strip()
DATA_DIR = Path(_ENV_DATA_DIR).expanduser() if _ENV_DATA_DIR else DIR
CFG_PATH = DATA_DIR / "config.json"
USER_DATA_PATH = DATA_DIR / "user_data.json"
_USER_DATA_LOCK = threading.Lock()
_INDEX_HTML_CACHE = {"mtime_ns": None, "token": None, "bytes": None, "gz": None}
_STATIC_ASSET_CACHE = {}
_INDEX_CACHE_LOCK = threading.Lock()
_API_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mastosky-api")
SCHEDULED_POSTS_PATH = DATA_DIR / "scheduled_posts.json"
_SCHEDULED_LOCK = threading.Lock()


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
    path = Path(path or CFG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(cfg, indent=2))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _default_user_data():
    return {
        "saved_posts": [],
        "drafts": [],
        "muted_words": [],
        "mute_mode": "warn",
        "preferences": {},
        "updated_at": 0,
    }


def _read_user_data_unlocked(path):
    base = _default_user_data()
    if not path.exists():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return base
    if not isinstance(raw, dict):
        return base
    if isinstance(raw.get("saved_posts"), list):
        base["saved_posts"] = raw["saved_posts"]
    if isinstance(raw.get("drafts"), list):
        base["drafts"] = raw["drafts"]
    if isinstance(raw.get("muted_words"), list):
        base["muted_words"] = [str(w).strip().lower() for w in raw["muted_words"] if isinstance(w, str) and w.strip()]
    if raw.get("mute_mode") in ("warn", "hide"):
        base["mute_mode"] = raw["mute_mode"]
    if isinstance(raw.get("preferences"), dict):
        base["preferences"] = raw["preferences"]
    if isinstance(raw.get("updated_at"), (int, float)):
        base["updated_at"] = int(raw["updated_at"])
    return base


def load_user_data(path=None):
    """Carrega dados sincronizáveis do utilizador (guardados, rascunhos, silenciamentos, preferências)."""
    path = Path(path or USER_DATA_PATH)
    with _USER_DATA_LOCK:
        return _read_user_data_unlocked(path)


def save_user_data(updates, path=None):
    """Atualiza e grava os dados do utilizador em disco com permissões 0600 de forma segura."""
    if not isinstance(updates, dict):
        raise ValueError("Payload inválido")
    path = Path(path or USER_DATA_PATH)
    with _USER_DATA_LOCK:
        current = _read_user_data_unlocked(path)
        if "saved_posts" in updates:
            if not isinstance(updates["saved_posts"], list):
                raise ValueError("saved_posts inválido")
            current["saved_posts"] = updates["saved_posts"][:1000]
        if "drafts" in updates:
            if not isinstance(updates["drafts"], list):
                raise ValueError("drafts inválido")
            current["drafts"] = updates["drafts"][:200]
        if "muted_words" in updates:
            if not isinstance(updates["muted_words"], list):
                raise ValueError("muted_words inválido")
            seen = set()
            clean_words = []
            for w in updates["muted_words"]:
                if isinstance(w, str):
                    cw = w.strip().lower()
                    if cw and cw not in seen:
                        seen.add(cw)
                        clean_words.append(cw)
            current["muted_words"] = clean_words[:500]
        if "mute_mode" in updates:
            if updates["mute_mode"] not in ("warn", "hide"):
                raise ValueError("mute_mode inválido")
            current["mute_mode"] = updates["mute_mode"]
        if "preferences" in updates:
            if not isinstance(updates["preferences"], dict):
                raise ValueError("preferences inválido")
            merged_prefs = dict(current.get("preferences") or {})
            for pk, pv in updates["preferences"].items():
                if isinstance(pk, str) and len(pk) <= 64:
                    merged_prefs[pk] = pv
            current["preferences"] = merged_prefs
        current["updated_at"] = int(time.time() * 1000)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = Path(f"{path}.tmp")
        write_config(current, tmp_path)
        os.replace(tmp_path, path)
        secure_config_perms(path)
        return current


def _read_scheduled_unlocked(path):
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "[]")
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def _write_scheduled_unlocked(items, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(f"{path}.tmp")
    write_config(items, tmp_path)
    os.replace(tmp_path, path)
    secure_config_perms(path)


def load_scheduled_posts(path=None):
    """Carrega a fila persistida de publicações agendadas."""
    path = Path(path or SCHEDULED_POSTS_PATH)
    with _SCHEDULED_LOCK:
        return _read_scheduled_unlocked(path)


def save_scheduled_posts(items, path=None):
    """Guarda a fila de publicações agendadas com permissões 0600."""
    if not isinstance(items, list):
        raise ValueError("Lista de agendamentos inválida")
    path = Path(path or SCHEDULED_POSTS_PATH)
    with _SCHEDULED_LOCK:
        clean_items = items[:200]
        _write_scheduled_unlocked(clean_items, path)
        return clean_items


def execute_post_payload(d, validate_only=False, target_override=None):
    """Valida e (se validate_only=False) publica um payload de post/fio/híbrido nas redes selecionadas."""
    if not isinstance(d, dict):
        return 400, {"error": "JSON inválido"}

    text = (d.get("text") or "").strip()
    ref = d.get("reply")
    if ref is not None and not (isinstance(ref, dict) and isinstance(ref.get("ref"), dict)
                                and isinstance(ref.get("network"), str)):
        return 400, {"error": "Resposta inválida."}
    spoiler = (d.get("spoiler") or "").strip() or None
    poll = d.get("poll")
    if poll is not None and not isinstance(poll, dict):
        return 400, {"error": "Sondagem inválida."}
    lang = d.get("lang")
    if lang is None:
        lang = CFG.get("default_lang")
    if lang is not None:
        if not isinstance(lang, str):
            return 400, {"error": "Idioma inválido."}
        lang = lang.strip().lower()
        if not lang or not re.match(r"^[a-z]{2}(-[a-z]{2})?$", lang):
            return 400, {"error": "Idioma inválido."}
    visibility = d.get("visibility")
    if visibility is not None:
        if not isinstance(visibility, str) or visibility not in ("public", "unlisted", "private", "direct"):
            return 400, {"error": "Visibilidade inválida."}
    quote = d.get("quote")
    if quote is not None and not isinstance(quote, dict):
        return 400, {"error": "Citação inválida."}
    link_card = d.get("link_card")
    if link_card is not None and not isinstance(link_card, dict):
        return 400, {"error": "Pré-visualização de ligação inválida."}

    if target_override is not None:
        targets = list(target_override)
    else:
        targets = [ref["network"]] if ref else d.get("targets", [])
    if (not isinstance(targets, list) or not targets
            or not all(isinstance(t, str) for t in targets)):
        return 400, {"error": "Escolhe pelo menos uma rede."}
    unknown = [t for t in targets if t not in CLIENTS]
    if unknown:
        return 400, {"error": "Rede não configurada: " + ", ".join(unknown)}

    def _parse_imgs(raw_images):
        if not raw_images:
            return []
        if not isinstance(raw_images, list):
            raise ValueError("Imagens inválidas.")
        parsed = []
        for img in raw_images:
            if not isinstance(img, dict):
                raise ValueError("Imagens inválidas.")
            raw_data = img.get("data", "")
            if not isinstance(raw_data, str):
                raise ValueError("Imagens inválidas.")
            if "," in raw_data:
                hdr, b64 = raw_data.split(",", 1)
                mime = hdr.split(";")[0].replace("data:", "") or "image/jpeg"
            else:
                mime = img.get("mime") or "image/jpeg"
                b64 = raw_data
            try:
                img_bytes = base64.b64decode(b64, validate=True)
            except (binascii.Error, ValueError):
                raise ValueError("Imagem com codificação inválida.")
            parsed.append({
                "bytes": img_bytes,
                "mime": mime,
                "alt": img.get("alt", ""),
                "aspectRatio": img.get("aspectRatio")
            })
        return parsed

    def _parse_video(raw_video):
        if not raw_video:
            return None
        if not isinstance(raw_video, dict):
            raise ValueError("Vídeo inválido.")
        raw_data = raw_video.get("data", "")
        if not isinstance(raw_data, str) or not raw_data.strip():
            raise ValueError("Dados do vídeo em falta.")
        if "," in raw_data:
            hdr, b64 = raw_data.split(",", 1)
            mime = hdr.split(";")[0].replace("data:", "") or "video/mp4"
        else:
            mime = raw_video.get("mime") or "video/mp4"
            b64 = raw_data
        try:
            vid_bytes = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Vídeo com codificação base64 inválida.")
        if len(vid_bytes) > 50 * 1024 * 1024:
            raise ValueError("O ficheiro de vídeo excede o tamanho máximo de 50 MB.")
        return {
            "bytes": vid_bytes,
            "mime": mime,
            "name": raw_video.get("name") or "video.mp4",
            "alt": raw_video.get("alt", "") or "",
            "aspectRatio": raw_video.get("aspectRatio")
        }

    def _parse_thread_list(raw_list):
        if not isinstance(raw_list, list) or not raw_list:
            raise ValueError("Fio inválido.")
        if len(raw_list) > 25:
            raise ValueError("Fio demasiado longo (máx. 25 posts).")
        parsed_list = []
        for idx, item in enumerate(raw_list):
            if not isinstance(item, dict):
                raise ValueError(f"Post #{idx+1} do fio inválido.")
            item_text = (item.get("text") or "").strip()
            item_imgs = _parse_imgs(item.get("images") or [])
            item_vid = _parse_video(item.get("video"))
            if item_imgs and item_vid:
                raise ValueError(f"O post #{idx+1} do fio não pode conter imagens e vídeo simultaneamente.")
            item_poll = item.get("poll") if idx == 0 else None
            item_quote = item.get("quote") if idx == 0 else quote
            if not item_text and not item_imgs and not item_vid and not (idx == 0 and (item_poll or item_quote)):
                raise ValueError(f"O post #{idx+1} do fio não tem conteúdo.")
            parsed_list.append({
                "text": item_text,
                "images": item_imgs,
                "video": item_vid,
                "spoiler": (item.get("spoiler") or "").strip() or spoiler,
                "poll": item_poll,
                "quote": item_quote,
                "link_card": (item.get("link_card") or link_card) if idx == 0 else None
            })
        return parsed_list

    raw_thread = d.get("thread")
    raw_thread_by_net = d.get("thread_by_network")
    thread_by_net = {}
    if raw_thread_by_net is not None:
        if not isinstance(raw_thread_by_net, dict):
            return 400, {"error": "Fio inválido."}
        for t in targets:
            if t in raw_thread_by_net:
                try:
                    thread_by_net[t] = _parse_thread_list(raw_thread_by_net[t])
                except ValueError as ve:
                    return 400, {"error": str(ve)}

    thread_items = None
    if raw_thread is not None:
        try:
            thread_items = _parse_thread_list(raw_thread)
        except ValueError as ve:
            return 400, {"error": str(ve)}
    elif any(t not in thread_by_net for t in targets):
        try:
            parsed_images = _parse_imgs(d.get("images") or [])
            parsed_video = _parse_video(d.get("video"))
        except ValueError as ve:
            return 400, {"error": str(ve)}
        if parsed_images and parsed_video:
            return 400, {"error": "Não é possível publicar imagens e vídeo no mesmo post."}
        if not text and not parsed_images and not parsed_video and not poll and not quote:
            return 400, {"error": "A publicação não tem conteúdo."}
        thread_items = [{
            "text": text,
            "images": parsed_images,
            "video": parsed_video,
            "spoiler": spoiler,
            "poll": poll,
            "quote": quote,
            "link_card": link_card
        }]

    if validate_only:
        return 200, {"ok": True}

    results = {}
    for t in targets:
        try:
            current_ref = ref["ref"] if ref else None
            root_bsky = None
            if t == "bluesky" and current_ref and "root" in current_ref:
                root_bsky = current_ref["root"]

            target_thread_items = thread_by_net.get(t, thread_items) or []
            for idx, item in enumerate(target_thread_items):
                item_text = item["text"]
                item_imgs = item["images"]
                item_vid = item.get("video")
                item_spoiler = item["spoiler"]
                item_poll = item["poll"]
                item_quote = item["quote"]
                kwargs = {"spoiler": item_spoiler, "poll": item_poll, "lang": lang, "quote": item_quote, "video": item_vid}
                if t == "mastodon" and visibility:
                    kwargs["visibility"] = visibility
                if t == "bluesky" and item.get("link_card"):
                    kwargs["link_card"] = item["link_card"]

                created = CLIENTS[t].post(item_text, current_ref, item_imgs, **kwargs)

                if t == "mastodon":
                    m_id = created.get("id") if hasattr(created, "get") else None
                    if m_id:
                        current_ref = {"id": str(m_id)}
                elif t == "bluesky":
                    b_uri = created.get("uri") if hasattr(created, "get") else None
                    b_cid = created.get("cid") if hasattr(created, "get") else None
                    if b_uri and b_cid:
                        if not root_bsky:
                            root_bsky = {"uri": b_uri, "cid": b_cid}
                        current_ref = {
                            "root": root_bsky,
                            "uri": b_uri,
                            "cid": b_cid
                        }

            results[t] = "ok"
        except Exception as e:
            results[t] = str(e)
    return 200, results


def mark_missed_scheduled_posts(now=None, path=None):
    """Marca agendamentos pendentes cujo horário já passou (>120s) no arranque como 'missed'."""
    now_ts = int(now if now is not None else time.time())
    path = Path(path or SCHEDULED_POSTS_PATH)
    changed = False
    with _SCHEDULED_LOCK:
        items = _read_scheduled_unlocked(path)
        for it in items:
            if it.get("status") == "pending" and int(it.get("scheduled_at") or 0) < (now_ts - 120):
                it["status"] = "missed"
                it["updated_at"] = now_ts
                changed = True
        if changed:
            _write_scheduled_unlocked(items, path)
    return changed


def _apply_scheduled_execution(item, now_ts):
    payload = item.get("payload") or {}
    prev_results = dict(item.get("results") or {})
    orig_targets = payload.get("targets") or ([payload["reply"]["network"]] if isinstance(payload.get("reply"), dict) else [])
    if item.get("status") == "partial" and prev_results:
        run_targets = [t for t in orig_targets if prev_results.get(t) != "ok"]
        if not run_targets:
            run_targets = list(orig_targets)
    else:
        run_targets = list(orig_targets)

    code, res = execute_post_payload(payload, target_override=run_targets)
    if code != 200:
        err_msg = res.get("error") or "Erro ao publicar agendamento."
        for t in run_targets:
            prev_results[t] = err_msg
        item["results"] = prev_results
        item["error"] = err_msg
        item["status"] = "partial" if any(v == "ok" for v in prev_results.values()) else "failed"
    else:
        merged_results = dict(prev_results)
        merged_results.update(res)
        item["results"] = merged_results
        good = [k for k, v in merged_results.items() if v == "ok"]
        bad = {k: v for k, v in merged_results.items() if v != "ok"}
        if not bad and good:
            item["status"] = "published"
            item["error"] = ""
            item["published_at"] = now_ts
        elif good and bad:
            item["status"] = "partial"
            item["error"] = "; ".join(f"{k}: {v}" for k, v in bad.items())
        else:
            item["status"] = "failed"
            item["error"] = "; ".join(f"{k}: {v}" for k, v in bad.items()) or "Erro desconhecido."
    item["updated_at"] = now_ts
    return item


def run_scheduled_item(item_id, now=None, path=None):
    """Executa imediatamente um item agendado (ou reenvia apenas redes falhadas em 'partial')."""
    now_ts = int(now if now is not None else time.time())
    path = Path(path or SCHEDULED_POSTS_PATH)
    with _SCHEDULED_LOCK:
        items = _read_scheduled_unlocked(path)
        target_idx = next((i for i, it in enumerate(items) if it.get("id") == item_id), None)
        if target_idx is None:
            return None
        target_copy = dict(items[target_idx])
    updated_item = _apply_scheduled_execution(target_copy, now_ts)
    with _SCHEDULED_LOCK:
        items = _read_scheduled_unlocked(path)
        for i, it in enumerate(items):
            if it.get("id") == item_id:
                items[i] = updated_item
                _write_scheduled_unlocked(items, path)
                break
    return updated_item


def process_due_scheduled_posts(now=None, path=None):
    """Processa agendamentos 'pending' cujo horário já chegou."""
    now_ts = int(now if now is not None else time.time())
    path = Path(path or SCHEDULED_POSTS_PATH)
    with _SCHEDULED_LOCK:
        items = _read_scheduled_unlocked(path)
        due_ids = [
            it.get("id") for it in items
            if it.get("status") == "pending" and int(it.get("scheduled_at") or 0) <= now_ts
        ]
    processed = []
    for item_id in due_ids:
        res = run_scheduled_item(item_id, now=now_ts, path=path)
        if res is not None:
            processed.append(res)
    return processed


def start_scheduler_thread():
    """Marca atrasados no arranque e inicia o ciclo em background (15s)."""
    try:
        mark_missed_scheduled_posts()
    except Exception:
        pass

    def _loop():
        while True:
            try:
                process_due_scheduled_posts()
            except Exception:
                pass
            time.sleep(15)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t


def load_cfg():
    if CFG_PATH.exists():
        secure_config_perms()
        try:
            return json.loads(CFG_PATH.read_text())
        except Exception:
            return {}
    return {}


MAX_BODY = 70 * 1024 * 1024  # limite do corpo dos pedidos POST (imagens e vídeos em base64 até 50MB)
CFG = load_cfg()
PORT = CFG.get("port", 8000)
LISTEN_HOST = "127.0.0.1"
LAN_MODE = False
SESSION_TOKEN = secrets.token_hex(32)  # Token criptográfico de sessão para proteção CSRF
VERSION = "1.1.0"
UPDATE_CACHE = {"checked_at": 0, "data": None}


def create_ssl_context():
    """Garante que o SSL tem certificados raiz válidos no macOS, Linux e Windows."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass

    cert_file = os.environ.get("SSL_CERT_FILE")
    if cert_file and os.path.exists(cert_file):
        try:
            return ssl.create_default_context(cafile=cert_file)
        except Exception:
            pass

    ctx = ssl.create_default_context()
    # No macOS, o bundle do sistema em /etc/ssl/cert.pem resolve a ausência de CA no Python padrão
    for ca_path in ("/etc/ssl/cert.pem", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(ca_path):
            try:
                ctx.load_verify_locations(ca_path)
                return ctx
            except Exception:
                pass
    return ctx


SSL_CTX = create_ssl_context()


def parse_semver(s):
    return [int(x) if x.isdigit() else 0 for x in re.findall(r"\d+", s or "0")]


def check_github_update(force=False):
    """Consulta a API do GitHub com cache de 1 hora para evitar rate limiting."""
    now = time.time()
    if not force and UPDATE_CACHE["data"] and (now - UPDATE_CACHE["checked_at"] < 3600):
        return UPDATE_CACHE["data"]

    url = "https://api.github.com/repos/gjmcosta/MastoSky/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"MastoSky/{VERSION} (+https://github.com/gjmcosta/MastoSky)",
            "Accept": "application/vnd.github.v3+json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=5, context=SSL_CTX) as resp:
            if resp.status == 200:
                d = json.loads(resp.read().decode("utf-8"))
                tag = (d.get("tag_name") or "").lstrip("v")
                has_update = False
                if tag:
                    has_update = parse_semver(tag) > parse_semver(VERSION)

                res = {
                    "current": VERSION,
                    "latest": tag or VERSION,
                    "has_update": has_update,
                    "url": d.get("html_url") or "https://github.com/gjmcosta/MastoSky/releases",
                    "name": d.get("name") or f"MastoSky v{tag}",
                    "notes": (d.get("body") or "")[:400]
                }
                UPDATE_CACHE["checked_at"] = now
                UPDATE_CACHE["data"] = res
                return res
    except Exception:
        pass

    fallback = {
        "current": VERSION,
        "latest": VERSION,
        "has_update": False,
        "url": "https://github.com/gjmcosta/MastoSky/releases",
        "name": "",
        "notes": ""
    }
    return fallback


def run_self_update():
    """Atualiza o MastoSky. Se estiver num repositório git, faz git pull.
    Caso contrário, descarrega o arquivo tarball da release mais recente."""
    is_git = (DIR / ".git").is_dir()
    if is_git:
        proc = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        if proc.returncode != 0:
            proc_reset = subprocess.run(
                ["git", "fetch", "origin", "main"],
                cwd=str(DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )
            if proc_reset.returncode == 0:
                subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=str(DIR), timeout=10)
            else:
                raise RuntimeError(proc.stderr or proc_reset.stderr or "Falha ao atualizar via Git.")
        return "MastoSky atualizado com sucesso via Git!"
    else:
        import io, tarfile
        url = "https://github.com/gjmcosta/MastoSky/archive/refs/heads/main.tar.gz"
        req = urllib.request.Request(url, headers={"User-Agent": f"MastoSky/{VERSION}"})
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
            data = resp.read()
        persist_dir = (DATA_DIR / "app_update") if DATA_DIR.resolve() != DIR.resolve() else None
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts
                if len(parts) > 1:
                    rel_path = Path(*parts[1:])
                    if rel_path.is_absolute() or ".." in rel_path.parts:
                        continue
                    # Nunca sobrescrever configurações e dados locais do utilizador
                    if rel_path.name in ("config.json", "user_data.json", "scheduled_posts.json"):
                        continue
                    targets = [DIR / rel_path]
                    if persist_dir is not None:
                        targets.append(persist_dir / rel_path)
                    if member.isdir():
                        for dest in targets:
                            dest.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        f = tar.extractfile(member)
                        if f:
                            content = f.read()
                            for dest in targets:
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                dest.write_bytes(content)
        return "MastoSky atualizado com sucesso!"


def schedule_process_restart(delay=0.8):
    """Reinicia o processo Python em background após enviar a resposta HTTP."""
    def _restart():
        time.sleep(delay)
        try:
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            os._exit(0)
    t = threading.Thread(target=_restart, daemon=True)
    t.start()


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
    def __init__(self, message, status=None, retry_after=None, body=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.body = body


def _retry_after(headers):
    try:
        v = headers.get("Retry-After") if headers else None
        return max(0, int(float(v))) if v is not None else None
    except (TypeError, ValueError):
        return None


RETRY_MAX_WAIT = 5  # segundos: só repete um GET num 429 se o servidor pedir menos do que isto


def _clean_http_error_summary(code, raw_err, content_type=""):
    """Formata um resumo legível para erros HTTP sem expor HTML bruto na UI."""
    text = (raw_err or "").strip()
    ct_lower = (content_type or "").lower()
    head_lower = text[:120].lstrip().lower()
    is_html = (
        "text/html" in ct_lower
        or head_lower.startswith(("<!doctype", "<html", "<head", "<body", "<?xml", "<"))
    )
    if is_html:
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""
        if title:
            if title.startswith(str(code)):
                return title[:160]
            return f"{code}: {title[:150]}"
        if code in (500, 502, 503, 504, 520, 521, 522, 523, 524):
            return f"{code}: Servidor temporariamente indisponível"
        return f"{code}: Resposta HTML inesperada do servidor"
    return f"{code}: {text[:200]}"


def http(method, url, data=None, token=None, headers=None, timeout=30):
    """Executa um pedido HTTP. Faz 1 retry se receber 429 com Retry-After razoável."""
    def _make_req():
        r = urllib.request.Request(url, method=method)
        r.add_header("User-Agent", "MastoSky/1.0")
        r.add_header("Accept-Encoding", "gzip")
        if token:
            r.add_header("Authorization", "Bearer " + token)
        if headers:
            for k, v in headers.items():
                r.add_header(k, v)
        b = None
        if data is not None:
            if isinstance(data, (bytes, bytearray)):
                b = data
                if not headers or "Content-Type" not in headers:
                    r.add_header("Content-Type", "application/octet-stream")
            else:
                b = json.dumps(data).encode()
                if not headers or "Content-Type" not in headers:
                    r.add_header("Content-Type", "application/json")
        return r, b

    host = urllib.parse.urlparse(url).netloc
    for attempt in (0, 1):
        req, body = _make_req()
        try:
            with urllib.request.urlopen(req, body, timeout=timeout, context=SSL_CTX) as r:
                raw = r.read()
                if not raw:
                    return {}
                enc = (r.headers.get("Content-Encoding") or "").lower() if hasattr(r, "headers") and hasattr(r.headers, "get") else ""
                if "gzip" in enc:
                    raw = zlib.decompress(raw, 16 + zlib.MAX_WBITS)
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, ValueError) as err:
                    ct = ""
                    if hasattr(r, "headers") and hasattr(r.headers, "get"):
                        ct = str(r.headers.get("Content-Type", ""))
                    raw_start = raw.lstrip()[:100].lower()
                    if "text/html" in ct.lower() or raw_start.startswith((b"<!doctype", b"<html", b"<head", b"<?xml", b"<")):
                        raise ApiError(f"O servidor devolveu uma página Web (HTML) em vez de dados JSON. Verifica se o endereço da instância ({host}) está correto e não inclui o teu perfil (@utilizador) ou outros caminhos.")
                    raise ApiError(f"Resposta inválida do servidor ({host}): {err}")
        except urllib.error.HTTPError as e:
            ra = _retry_after(e.headers)
            if e.code == 429 and method == "GET" and attempt == 0 and ra is not None and ra <= RETRY_MAX_WAIT:
                time.sleep(ra)
                continue
            raw_err = e.read()[:8192].decode(errors='replace')
            err_ct = ""
            if e.headers and hasattr(e.headers, "get"):
                err_ct = str(e.headers.get("Content-Type", ""))
            msg = _clean_http_error_summary(e.code, raw_err, err_ct)
            if e.code == 429:
                msg += f" (limite de pedidos; tenta de novo{f' dentro de {ra} s' if ra is not None else ' mais tarde'})"
            raise ApiError(msg, status=e.code, retry_after=ra, body=raw_err)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            if isinstance(e, urllib.error.URLError) and "certificate verify failed" in str(e).lower() and attempt == 0:
                try:
                    unverified_ctx = ssl._create_unverified_context()
                    retry_req, retry_body = _make_req()
                    with urllib.request.urlopen(retry_req, retry_body, timeout=timeout, context=unverified_ctx) as r:
                        raw = r.read()
                        if not raw:
                            return {}
                        try:
                            return json.loads(raw)
                        except (json.JSONDecodeError, ValueError) as err:
                            raise ApiError(f"Resposta inválida do servidor ({host}): {err}")
                except Exception:
                    pass
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


def build_bsky_facets(text, resolve_handle_fn=None):
    """Extrai facets (links, menções @handle e tags #hashtag) para o Bluesky."""
    if not text:
        return []
    facets = []
    for m in _URL_RE.finditer(text):
        url = m.group().rstrip(".,;:!?)")
        b_start, b_end = byte_span(text, m.start(), m.start() + len(url))
        facets.append({"index": {"byteStart": b_start, "byteEnd": b_end},
                       "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]})
    for m in _HANDLE_RE.finditer(text):
        handle = m.group(1)
        did = resolve_handle_fn(handle) if resolve_handle_fn else None
        if did:
            b_start, b_end = byte_span(text, m.start(), m.end())
            facets.append({"index": {"byteStart": b_start, "byteEnd": b_end},
                           "features": [{"$type": "app.bsky.richtext.facet#mention", "did": did}]})
    for m in _HASHTAG_RE.finditer(text):
        tag = m.group(1)
        b_start, b_end = byte_span(text, m.start(), m.end())
        facets.append({"index": {"byteStart": b_start, "byteEnd": b_end},
                       "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag}]})
    clean_facets = []
    last_end = 0
    for f in sorted(facets, key=lambda f: (f["index"]["byteStart"], -f["index"]["byteEnd"])):
        st, en = f["index"]["byteStart"], f["index"]["byteEnd"]
        if st >= last_end and en > st:
            clean_facets.append(f)
            last_end = en
    return clean_facets


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


def plain(h, strip_quote_inline=False, strip_re=False):
    cleaned = clean(h, strip_quote_inline=strip_quote_inline)
    if strip_re:
        cleaned = strip_re_prefix(cleaned)
    cleaned = re.sub(r"</?a\b[^>]*>", "", cleaned, flags=re.I)
    cleaned = re.sub(r"(?:<br\s*/?>[ \t]*){2,}", "\n\n", cleaned, flags=re.I)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.I)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", cleaned))
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in txt.split("\n")]
    return "\n".join(lines).strip()


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


_LINK_PREVIEW_CACHE = {}


def _check_ip_public(ip_obj):
    """Rejeita endereços IP privados, loopback, link-local ou Tailscale."""
    mapped = getattr(ip_obj, "ipv4_mapped", None)
    if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj in _TAILSCALE_NET or (
        mapped is not None and (mapped.is_private or mapped.is_loopback or mapped.is_link_local or mapped in _TAILSCALE_NET)
    ):
        raise ValueError("Acesso a endereços de rede privada não permitido.")


def _validate_remote_http_url(url_str):
    """Valida URL http(s) pública e bloqueia destinos locais/privados/Tailscale (incluindo via DNS)."""
    u = safe_url(url_str)
    if not u:
        raise ValueError("URL inválida.")
    p = urllib.parse.urlparse(u)
    host = (p.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("Host inválido.")
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".local") or host.endswith(".ts.net"):
        raise ValueError("Acesso a endereços locais não permitido.")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        _check_ip_public(ip)
    else:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            infos = []
        for info in infos:
            addr = info[4][0].split("%", 1)[0]
            try:
                resolved_ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            _check_ip_public(resolved_ip)
    return u, p


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Revalida o destino de cada redirecionamento HTTP contra SSRF."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_remote_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_ORIG_URLOPEN = urllib.request.urlopen


def _urlopen_remote(req, timeout=10):
    """Abre um pedido remoto exigindo TLS válido e validando redirecionamentos."""
    if urllib.request.urlopen is not _ORIG_URLOPEN:
        return urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=SSL_CTX),
        _SafeRedirectHandler(),
    )
    return opener.open(req, timeout=timeout)


class _LinkPreviewParser(HTMLParser):
    """Extrai metadados OpenGraph / Twitter Card / HTML <title> de uma página."""
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.in_title = False
        self.title_parts = []

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        if tag_l == "title":
            self.in_title = True
            return
        if tag_l != "meta":
            return
        ad = {k.lower(): (v or "") for k, v in attrs if k}
        key = (ad.get("property") or ad.get("name") or "").strip().lower()
        val = (ad.get("content") or "").strip()
        if key and val and key not in self.meta:
            self.meta[key] = val

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title and len(self.title_parts) < 16:
            self.title_parts.append(data)


def fetch_link_preview(url_str):
    """Obtém título, descrição, domínio e imagem de pré-visualização de uma ligação externa."""
    u, p = _validate_remote_http_url(url_str)
    now = time.time()
    cached = _LINK_PREVIEW_CACHE.get(u)
    if cached and (now - cached["ts"] < 1800):
        return cached["data"]

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MastoSky/1.0; +https://github.com/gjmcosta/MastoSky)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    }
    req = urllib.request.Request(u, headers=headers)
    try:
        resp = _urlopen_remote(req, timeout=6)
    except Exception as e:
        raise ValueError(f"Não foi possível obter pré-visualização da ligação: {e}")

    with resp:
        ctype = (resp.headers.get_content_type() or "").lower()
        if ctype and not ("html" in ctype or ctype == "application/octet-stream"):
            domain = p.netloc.lower()
            out = {"ok": True, "url": u, "domain": domain, "title": domain, "description": "", "image": None}
            _LINK_PREVIEW_CACHE[u] = {"ts": now, "data": out}
            return out
        raw = resp.read(256 * 1024)
        charset = resp.headers.get_content_charset() or "utf-8"

    text_html = raw.decode(charset, errors="replace")
    parser = _LinkPreviewParser()
    try:
        parser.feed(text_html)
    except Exception:
        pass

    m = parser.meta
    raw_title = (
        m.get("og:title")
        or m.get("twitter:title")
        or m.get("title")
        or "".join(parser.title_parts)
    )
    title = html.unescape(re.sub(r"\s+", " ", raw_title or "")).strip()[:300]
    raw_desc = (
        m.get("og:description")
        or m.get("twitter:description")
        or m.get("description")
        or ""
    )
    desc = html.unescape(re.sub(r"\s+", " ", raw_desc)).strip()[:600]
    raw_img = (
        m.get("og:image:secure_url")
        or m.get("og:image")
        or m.get("twitter:image")
        or m.get("twitter:image:src")
        or ""
    ).strip()
    img_url = safe_url(urllib.parse.urljoin(u, raw_img)) if raw_img else None
    domain = (p.netloc or "").lower().removeprefix("www.")
    out = {
        "ok": True,
        "url": u,
        "domain": domain,
        "title": title or domain,
        "description": desc,
        "image": img_url,
    }
    if len(_LINK_PREVIEW_CACHE) > 200:
        _LINK_PREVIEW_CACHE.clear()
    _LINK_PREVIEW_CACHE[u] = {"ts": now, "data": out}
    return out


_READER_CACHE = {}


class _ReaderParser(HTMLParser):
    """Extrai conteúdo principal limpo de artigos HTML ignorando navegação, scripts e rodapés."""
    _SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "aside", "form", "iframe", "button", "header"}
    _BLOCK_TAGS = {"h1", "h2", "h3", "h4", "p", "blockquote", "li", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.title_parts = []
        self._in_title = False
        self._skip_depth = 0
        self._article_depth = 0
        self._main_depth = 0
        self._cur_tag = None
        self._cur_parts = []
        self._cur_in_article = False
        self._cur_in_main = False
        self.article_blocks = []
        self.main_blocks = []
        self.body_blocks = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        ad = {k.lower(): (v or "") for k, v in attrs if k}
        if t == "title":
            self._in_title = True
        elif t == "meta":
            key = (ad.get("property") or ad.get("name") or "").strip().lower()
            val = ad.get("content", "").strip()
            if key and val and key not in self.meta:
                self.meta[key] = val
        if t in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if t == "article":
            self._article_depth += 1
        elif t == "main":
            self._main_depth += 1
        if t in self._BLOCK_TAGS and self._cur_tag is None:
            self._cur_tag = "h2" if t in ("h1", "h2", "h3", "h4") else t
            self._cur_parts = []
            self._cur_in_article = self._article_depth > 0
            self._cur_in_main = self._main_depth > 0

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "title":
            self._in_title = False
        if t in self._SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return
        if t == "article" and self._article_depth > 0:
            self._article_depth -= 1
        elif t == "main" and self._main_depth > 0:
            self._main_depth -= 1

        mapped = "h2" if t in ("h1", "h2", "h3", "h4") else t
        if self._cur_tag == mapped:
            txt = html.unescape(re.sub(r"\s+", " ", "".join(self._cur_parts))).strip()
            if txt and (len(txt) >= 15 or self._cur_tag in ("h2", "li", "blockquote")):
                blk = {"tag": self._cur_tag, "text": txt}
                if self._cur_in_article:
                    self.article_blocks.append(blk)
                if self._cur_in_main:
                    self.main_blocks.append(blk)
                self.body_blocks.append(blk)
            self._cur_tag = None
            self._cur_parts = []

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        elif self._skip_depth == 0 and self._cur_tag is not None:
            self._cur_parts.append(data)


def fetch_article_reader(url_str):
    """Obtém e extrai o texto limpo de um artigo web externo para o Reader View."""
    u, p = _validate_remote_http_url(url_str)
    now = time.time()
    cached = _READER_CACHE.get(u)
    if cached and (now - cached["ts"] < 1800):
        return cached["data"]

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MastoSky/1.0; +https://github.com/gjmcosta/MastoSky)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    }
    req = urllib.request.Request(u, headers=headers)
    try:
        resp = _urlopen_remote(req, timeout=8)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 451):
            raise ValueError(f"Este site bloqueia a leitura direta (HTTP {e.code} — paywall ou acesso restrito). Usa «Abrir original ↗» para ler no navegador.")
        if e.code in (404, 410):
            raise ValueError(f"Artigo não encontrado (HTTP {e.code}).")
        if e.code == 429:
            raise ValueError("Demasiados pedidos ao site de origem (HTTP 429). Tenta novamente mais tarde.")
        raise ValueError(f"Não foi possível carregar o artigo (HTTP {e.code}).")
    except Exception as e:
        raise ValueError(f"Não foi possível carregar o artigo: {e}")

    with resp:
        ctype = (resp.headers.get_content_type() or "").lower()
        if ctype and not ("html" in ctype or "xml" in ctype or ctype == "application/octet-stream"):
            raise ValueError("Esta ligação não aponta para um artigo HTML legível.")
        raw = resp.read(1536 * 1024)
        charset = resp.headers.get_content_charset() or "utf-8"

    text_html = raw.decode(charset, errors="replace")
    parser = _ReaderParser()
    try:
        parser.feed(text_html)
    except Exception:
        pass

    m = parser.meta
    raw_title = m.get("og:title") or m.get("twitter:title") or m.get("title") or "".join(parser.title_parts)
    title = html.unescape(re.sub(r"\s+", " ", raw_title or "")).strip()[:300]
    author = html.unescape(re.sub(r"\s+", " ", m.get("author") or m.get("article:author") or "")).strip()[:120]
    site_name = html.unescape(re.sub(r"\s+", " ", m.get("og:site_name") or "")).strip()[:120]
    pub_date = (m.get("article:published_time") or m.get("date") or "")[:32]
    raw_img = (m.get("og:image:secure_url") or m.get("og:image") or m.get("twitter:image") or "").strip()
    img_url = safe_url(urllib.parse.urljoin(u, raw_img)) if raw_img else None
    domain = (p.netloc or "").lower().removeprefix("www.")

    blocks = parser.article_blocks
    if sum(len(b["text"]) for b in blocks) < 200:
        blocks = parser.main_blocks if sum(len(b["text"]) for b in parser.main_blocks) >= 200 else parser.body_blocks

    # Deduplicar blocos repetidos e limitar tamanho total
    deduped = []
    seen_txt = set()
    word_count = 0
    for b in blocks:
        if b["text"] in seen_txt:
            continue
        seen_txt.add(b["text"])
        deduped.append(b)
        word_count += len(b["text"].split())
        if len(deduped) >= 150:
            break

    if not deduped:
        desc = html.unescape(re.sub(r"\s+", " ", m.get("og:description") or m.get("description") or "")).strip()
        if desc:
            deduped = [{"tag": "p", "text": desc}]
            word_count = len(desc.split())

    reading_minutes = max(1, round(word_count / 200)) if word_count else 1
    out = {
        "ok": True,
        "url": u,
        "domain": domain,
        "site_name": site_name or domain,
        "title": title or domain,
        "author": author,
        "published_at": pub_date,
        "image": img_url,
        "reading_minutes": reading_minutes,
        "word_count": word_count,
        "blocks": deduped,
    }
    if len(_READER_CACHE) > 100:
        _READER_CACHE.clear()
    _READER_CACHE[u] = {"ts": now, "data": out}
    return out


def proxy_fetch_image(url_str):
    """Descarrega com segurança uma imagem remota para o gerador de cartões da publicação cruzada."""
    u, p = _validate_remote_http_url(url_str)

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": f"{p.scheme}://{p.netloc}/"
    }
    req = urllib.request.Request(u, headers=headers)
    try:
        resp = _urlopen_remote(req, timeout=10)
    except Exception as e:
        raise ValueError(f"Não foi possível obter imagem remota: {e}")

    with resp:
        ctype = resp.headers.get_content_type()
        data = resp.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("Imagem excede o limite máximo de 10MB.")

        if data.startswith(b"\xff\xd8\xff"):
            ctype = "image/jpeg"
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            ctype = "image/png"
        elif data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
            ctype = "image/gif"
        elif len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            ctype = "image/webp"
        elif len(data) >= 16 and b"ftypavif" in data[:16]:
            ctype = "image/avif"
        elif not ctype or not (ctype.startswith("image/") or ctype == "application/octet-stream"):
            raise ValueError("O conteúdo remoto não é uma imagem válida.")

        return data, ctype if (ctype and ctype.startswith("image/")) else "image/jpeg"


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
    uri = rec.get("uri")
    cid = rec.get("cid")
    viewer = rec.get("viewer") or {}
    like_uri = viewer.get("like")
    repost_uri = viewer.get("repost")
    ref_obj = {"uri": uri, "cid": cid} if uri else None
    if ref_obj and like_uri:
        ref_obj["like_uri"] = like_uri
    if ref_obj and repost_uri:
        ref_obj["repost_uri"] = repost_uri
    return {
        "network": "bluesky",
        "name": author.get("displayName") or handle,
        "handle": "@" + handle if handle else "",
        "author_id": author.get("did") or handle,
        "author_handle": handle,
        "avatar": safe_url(author.get("avatar")),
        "text": text,
        "html": render_bsky_text(text, facets) if text else "",
        "time": val.get("createdAt") or rec.get("createdAt") or rec.get("indexedAt"),
        "url": f"https://bsky.app/profile/{handle}/post/{rec.get('uri', '').split('/')[-1]}" if handle and uri else None,
        "ref": ref_obj,
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

    plain_text = ((f"[{qs['spoiler_text']}] " if qs.get("spoiler_text") else "") + plain(qs.get("content"), strip_quote_inline=True, strip_re=True)).strip()
    ref_obj = {"id": qs.get("id")} if qs.get("id") else None
    out = {
        "network": "mastodon",
        "name": q_name,
        "handle": "@" + q_acc.get("acct", ""),
        "author_id": q_acc.get("id") or q_acc.get("acct"),
        "author_handle": q_acc.get("acct"),
        "avatar": safe_url(q_acc.get("avatar")),
        "text": plain_text,
        "html": q_html,
        "time": qs.get("created_at"),
        "url": safe_url(qs.get("url")),
        "ref": ref_obj,
        "media": safe_media_list(q_media),
        "cw": (qs.get("spoiler_text") or "").strip(),
    }
    if q_name_html:
        out["name_html"] = q_name_html
    return out


class Bsky:
    name = "bluesky"

    def __init__(self, c):
        self.c, self.jwt, self.refresh_jwt, self.did = c, None, None, None
        self.host = c.get("service", "https://bsky.social")
        self.pds = None
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
            pds_endpoint = None
            for s in (r.get("didDoc", {}).get("service") or []):
                if s.get("type") == "AtprotoPersonalDataServer" or s.get("id") == "#atproto_pds":
                    pds_endpoint = s.get("serviceEndpoint")
                    break
            self.pds = pds_endpoint or self.host

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
                    if "didDoc" in r:
                        for s in (r.get("didDoc", {}).get("service") or []):
                            if s.get("type") == "AtprotoPersonalDataServer" or s.get("id") == "#atproto_pds":
                                self.pds = s.get("serviceEndpoint")
                                break
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

    def call(self, method, nsid, data=None, params=None, headers=None):
        url = f"{self.host}/xrpc/{nsid}" + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        return self._authed(lambda jwt: http(method, url, data, jwt, headers=headers))

    def call_chat(self, method, nsid, data=None, params=None):
        headers = {"atproto-proxy": "did:web:api.bsky.chat#bsky_chat"}
        self._ensure()
        pds_host = self.pds or self.host
        url = f"{pds_host}/xrpc/{nsid}" + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        try:
            return self._authed(lambda jwt: http(method, url, data, jwt, headers=headers))
        except Exception as e:
            err_msg = str(e)
            if any(term in err_msg for term in ("AuthFactorTokenRequired", "InvalidToken", "Bad token scope", "Token lacks chat", "401", "403")):
                raise ApiError("A tua App Password do Bluesky não tem permissões para aceder a mensagens. Cria uma nova App Password em bsky.app com a opção de Direct Messages ativada.")
            raise

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

    def get_custom_feeds(self):
        r = self.call("GET", "app.bsky.actor.getPreferences")
        prefs = r.get("preferences", [])
        uris = []
        pinned_set = set()
        for pref in prefs:
            ptype = pref.get("$type", "")
            if ptype == "app.bsky.actor.defs#savedFeedsPrefV2":
                for item in pref.get("items", []):
                    if item.get("type") == "feed" and item.get("value"):
                        uri = item["value"]
                        if uri not in uris:
                            uris.append(uri)
                        if item.get("pinned"):
                            pinned_set.add(uri)
            elif ptype == "app.bsky.actor.defs#savedFeedsPref":
                for uri in pref.get("pinned", []):
                    if uri and uri.startswith("at://"):
                        pinned_set.add(uri)
                        if uri not in uris:
                            uris.append(uri)
                for uri in pref.get("saved", []):
                    if uri and uri.startswith("at://") and uri not in uris:
                        uris.append(uri)
        if not uris:
            return []
        gens_resp = self.call("GET", "app.bsky.feed.getFeedGenerators", params={"feeds": uris[:25]})
        by_uri = {f.get("uri"): f for f in gens_resp.get("feeds", []) if f.get("uri")}
        out = []
        for uri in uris[:25]:
            fg = by_uri.get(uri)
            if not fg:
                continue
            out.append({
                "id": uri,
                "network": "bluesky",
                "name": fg.get("displayName") or uri.rsplit("/", 1)[-1],
                "description": fg.get("description") or "",
                "avatar": safe_url(fg.get("avatar")),
                "pinned": uri in pinned_set,
            })
        out.sort(key=lambda x: (not x["pinned"], x["name"].lower()))
        return out

    def custom_feed(self, feed_uri, cursor=None):
        if not feed_uri or not str(feed_uri).startswith("at://"):
            raise ValueError("URI de feed Bluesky inválido.")
        params = {"feed": str(feed_uri), "limit": 40}
        if cursor:
            params["cursor"] = cursor
        r = self.call("GET", "app.bsky.feed.getFeed", params=params)
        feed = r.get("feed", [])
        return [self.item(it["post"], it.get("reason"), it.get("reply")) for it in feed], r.get("cursor")

    def thread(self, ref):
        uri = None
        if isinstance(ref, str):
            uri = ref
        elif isinstance(ref, dict):
            uri = ref.get("uri") or ref.get("url")
        if uri and "bsky.app/profile/" in str(uri):
            m = re.search(r"bsky\.app/profile/([^/?#]+)/post/([^/?#]+)", str(uri))
            if m:
                uri = f"at://{m.group(1)}/app.bsky.feed.post/{m.group(2)}"
        if not uri:
            raise RuntimeError("Referência de post inválida para Bluesky.")
        ok = "app.bsky.feed.defs#threadViewPost"
        r = self.call("GET", "app.bsky.feed.getPostThread",
                   params={"uri": uri, "depth": 8, "parentHeight": 30})["thread"]
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
        actor_clean = str(actor).strip().lstrip("@")
        actor_clean = urllib.parse.unquote(actor_clean)
        if actor_clean.startswith("http://") or actor_clean.startswith("https://"):
            m = re.search(r"/profile/([^/?#]+)", actor_clean)
            if m:
                actor_clean = urllib.parse.unquote(m.group(1))
        p = self.call("GET", "app.bsky.actor.getProfile", params={"actor": actor_clean})
        desc = p.get("description") or ""
        bio_html = render_bsky_text(desc) if desc else ""
        viewer = p.get("viewer") or {}
        follow_uri = viewer.get("following")
        target_did = p.get("did") or ""
        is_self = (target_did == self.did) if (self.did and target_did) else False
        return {
            "network": "bluesky",
            "did": target_did,
            "name": p.get("displayName") or p.get("handle") or "",
            "handle": "@" + (p.get("handle") or ""),
            "avatar": safe_url(p.get("avatar")),
            "banner": safe_url(p.get("banner")),
            "bio": bio_html,
            "followers": p.get("followersCount", 0),
            "following": p.get("followsCount", 0),
            "posts_count": p.get("postsCount", 0),
            "url": f"https://bsky.app/profile/{p.get('handle')}",
            "is_following": bool(follow_uri),
            "follow_uri": follow_uri,
            "is_self": is_self
        }

    def user_feed(self, actor, cursor=None):
        self._ensure()
        actor_clean = str(actor).strip().lstrip("@")
        actor_clean = urllib.parse.unquote(actor_clean)
        if actor_clean.startswith("http://") or actor_clean.startswith("https://"):
            m = re.search(r"/profile/([^/?#]+)", actor_clean)
            if m:
                actor_clean = urllib.parse.unquote(m.group(1))
        params = {"actor": actor_clean, "limit": 40}
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

    def search(self, q, search_type="all", limit=25):
        self._ensure()
        clean_q = q.strip()
        if not clean_q:
            return {"posts": [], "actors": [], "hashtags": []}

        posts = []
        actors = []
        hashtags = []

        if search_type in ("all", "posts", "hashtags"):
            try:
                params = {"q": clean_q, "limit": min(limit, 40)}
                if clean_q.startswith("#"):
                    params["tag"] = [clean_q.lstrip("#")]
                res = self.call("GET", "app.bsky.feed.searchPosts", params=params)
                posts = [self.item(p) for p in res.get("posts", [])]
            except Exception:
                pass

        if search_type in ("all", "actors"):
            try:
                actor_q = clean_q.lstrip("@")
                res = self.call("GET", "app.bsky.actor.searchActors", params={"q": actor_q, "limit": min(limit, 30)})
                actors = [{
                    "network": "bluesky",
                    "did": a.get("did"),
                    "handle": "@" + (a.get("handle") or ""),
                    "raw_handle": a.get("handle") or "",
                    "name": a.get("displayName") or a.get("handle") or "",
                    "avatar": safe_url(a.get("avatar")),
                    "description": a.get("description") or "",
                    "url": f"https://bsky.app/profile/{a.get('handle')}"
                } for a in res.get("actors", [])]
            except Exception:
                pass

        if clean_q.startswith("#") and search_type in ("all", "hashtags"):
            tag_name = clean_q.lstrip("#")
            hashtags.append({
                "network": "bluesky",
                "name": tag_name,
                "url": f"https://bsky.app/hashtag/{tag_name}"
            })

        return {"posts": posts, "actors": actors, "hashtags": hashtags}

    def upload_blob(self, raw_bytes, mime="image/jpeg"):
        url = f"{self.host}/xrpc/com.atproto.repo.uploadBlob"
        r = self._authed(lambda jwt: http("POST", url, data=raw_bytes, token=jwt, headers={"Content-Type": mime}))
        return r["blob"]

    def upload_video(self, raw_bytes, mime="video/mp4", name="video.mp4", max_wait=120):
        """Faz upload de vídeo para o microsserviço do Bluesky (video.bsky.app) e aguarda conclusão."""
        self._ensure()
        # 1. Obter serviceAuth token com escopo para did:web:video.bsky.app
        auth_url = f"{self.host}/xrpc/com.atproto.server.getServiceAuth"
        auth_res = self._authed(lambda jwt: http(
            "GET",
            auth_url + "?aud=did:web:video.bsky.app&lxm=com.atproto.repo.uploadBlob",
            token=jwt
        ))
        service_token = auth_res.get("token")
        if not service_token:
            raise ApiError("Não foi possível obter autorização para o serviço de vídeo do Bluesky.")

        # 2. Upload do vídeo binário para video.bsky.app
        did_param = urllib.parse.quote(self.did)
        name_param = urllib.parse.quote(name or "video.mp4")
        upload_url = f"https://video.bsky.app/xrpc/app.bsky.video.uploadVideo?did={did_param}&name={name_param}"
        upload_headers = {
            "Content-Type": mime or "video/mp4",
            "Content-Length": str(len(raw_bytes))
        }
        res = http("POST", upload_url, data=raw_bytes, token=service_token, headers=upload_headers, timeout=120)
        job_id = res.get("jobId") or (res.get("jobStatus") or {}).get("jobId")
        if not job_id:
            if "jobStatus" in res and res["jobStatus"].get("blob"):
                return res["jobStatus"]["blob"]
            raise ApiError("O serviço de vídeo do Bluesky não devolveu identificador de processamento (jobId).")

        # 3. Consultar getJobStatus até terminar o processamento
        status_url = f"https://video.bsky.app/xrpc/app.bsky.video.getJobStatus?jobId={urllib.parse.quote(job_id)}"
        start_t = time.time()
        while time.time() - start_t < max_wait:
            time.sleep(2)
            try:
                st = http("GET", status_url, timeout=15)
                job_st = st.get("jobStatus") or {}
                state = (job_st.get("state") or "").upper()
                if "COMPLETE" in state or state == "JOB_STATE_COMPLETED":
                    blob = job_st.get("blob")
                    if blob:
                        return blob
                    raise ApiError("O processamento do vídeo terminou mas o blob não foi devolvido.")
                elif "FAIL" in state or state == "JOB_STATE_FAILED":
                    err = job_st.get("error") or job_st.get("message") or "Falha na codificação do vídeo."
                    raise ApiError(f"Erro no processamento do vídeo no Bluesky: {err}")
            except ApiError as e:
                if "Erro no processamento" in str(e):
                    raise
            except Exception:
                pass

        raise ApiError("O processamento do vídeo no Bluesky excedeu o tempo limite (máx. 2 minutos).")

    def post(self, text, ref=None, images=None, spoiler=None, poll=None, lang=None, quote=None, video=None, link_card=None):
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
        clean_facets = build_bsky_facets(final_text, self.resolve_handle)
        rec = {"$type": "app.bsky.feed.post", "text": final_text, "createdAt": now_iso()}
        if clean_facets:
            rec["facets"] = clean_facets
        if lang:
            rec["langs"] = [lang]
        if ref:
            rec["reply"] = {"root": ref["root"], "parent": {"uri": ref["uri"], "cid": ref["cid"]}}
        
        embed_media = None
        if video and video.get("bytes"):
            v_blob = self.upload_video(video["bytes"], video.get("mime", "video/mp4"), video.get("name", "video.mp4"))
            embed_media = {
                "$type": "app.bsky.embed.video",
                "video": v_blob
            }
            if video.get("alt"):
                embed_media["alt"] = video["alt"]
            if video.get("aspectRatio"):
                embed_media["aspectRatio"] = video["aspectRatio"]
        elif images:
            embed_imgs = []
            for img in images:
                blob = self.upload_blob(img["bytes"], img.get("mime", "image/jpeg"))
                item = {"alt": img.get("alt", "") or "", "image": blob}
                if img.get("aspectRatio"):
                    item["aspectRatio"] = img["aspectRatio"]
                embed_imgs.append(item)
            if embed_imgs:
                embed_media = {"$type": "app.bsky.embed.images", "images": embed_imgs}

        if quote and quote.get("network") == "bluesky" and quote.get("ref", {}).get("uri"):
            q_record = {
                "$type": "app.bsky.embed.record",
                "record": {"uri": quote["ref"]["uri"], "cid": quote["ref"]["cid"]}
            }
            if embed_media:
                rec["embed"] = {
                    "$type": "app.bsky.embed.recordWithMedia",
                    "record": q_record,
                    "media": embed_media
                }
            else:
                rec["embed"] = q_record
        elif quote and quote.get("network") == "mastodon":
            if not embed_media and quote.get("url"):
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
            elif embed_media:
                rec["embed"] = embed_media
                if quote.get("url") and quote["url"] not in rec["text"]:
                    rec["text"] = (rec["text"] + "\n\n" + quote["url"]).strip()
        elif embed_media:
            rec["embed"] = embed_media
        elif not quote and isinstance(link_card, dict):
            card_url = safe_url(link_card.get("url"))
            if card_url:
                ext = {
                    "uri": card_url,
                    "title": (str(link_card.get("title") or link_card.get("domain") or card_url)).strip()[:300],
                    "description": (str(link_card.get("description") or "")).strip()[:600],
                }
                card_img = safe_url(link_card.get("image"))
                if card_img:
                    try:
                        img_bytes, img_mime = proxy_fetch_image(card_img)
                        if img_bytes and len(img_bytes) <= 950_000:
                            ext["thumb"] = self.upload_blob(img_bytes, img_mime)
                    except Exception:
                        pass
                rec["embed"] = {
                    "$type": "app.bsky.embed.external",
                    "external": ext,
                }

        return self.call("POST", "com.atproto.repo.createRecord",
               {"repo": self.did, "collection": "app.bsky.feed.post", "record": rec})

    def act(self, action, ref):
        self._ensure()
        if action in ("like", "boost"):
            col = {"like": "app.bsky.feed.like", "boost": "app.bsky.feed.repost"}[action]
            uri = ref.get("uri")
            cid = ref.get("cid")
            if not cid and uri:
                try:
                    res = self.call("GET", "app.bsky.feed.getPosts", params=[("uris", uri)])
                    posts = res.get("posts", [])
                    if posts:
                        cid = posts[0].get("cid")
                except Exception:
                    pass
            if not uri or not cid:
                raise ApiError("Referência de post incompleta para Bluesky (requer uri e cid).")
            return self.call("POST", "com.atproto.repo.createRecord", {
                "repo": self.did, "collection": col,
                "record": {"$type": col, "subject": {"uri": uri, "cid": cid}, "createdAt": now_iso()}})
        elif action in ("unlike", "unboost"):
            col = {"unlike": "app.bsky.feed.like", "unboost": "app.bsky.feed.repost"}[action]
            target_uri = ref.get("like_uri" if action == "unlike" else "repost_uri")
            if not target_uri and ref.get("uri"):
                try:
                    res = self.call("GET", "app.bsky.feed.getPosts", params=[("uris", ref["uri"])])
                    posts = res.get("posts", [])
                    if posts:
                        viewer = posts[0].get("viewer") or {}
                        target_uri = viewer.get("like" if action == "unlike" else "repost")
                except Exception:
                    pass
            if not target_uri:
                target_uri = ref.get("uri")
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

    def follow(self, actor):
        self._ensure()
        target_did = actor
        if not target_did.startswith("did:"):
            target_did = self.resolve_handle(actor)
            if not target_did:
                prof = self.user_profile(actor)
                target_did = prof.get("did") or actor
        return self.call("POST", "com.atproto.repo.createRecord", {
            "repo": self.did,
            "collection": "app.bsky.graph.follow",
            "record": {
                "$type": "app.bsky.graph.follow",
                "subject": target_did,
                "createdAt": now_iso()
            }
        })

    def unfollow(self, actor, follow_uri=None):
        self._ensure()
        target_uri = follow_uri
        if not target_uri:
            prof = self.user_profile(actor)
            target_uri = prof.get("follow_uri")
        if not target_uri:
            raise ApiError("Registo de follow não encontrado para remover.")
        rkey = target_uri.split("/")[-1]
        return self.call("POST", "com.atproto.repo.deleteRecord", {
            "repo": self.did,
            "collection": "app.bsky.graph.follow",
            "rkey": rkey
        })

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

            target_post = None
            if kind in ("reply", "mention", "quote"):
                rec = n.get("record") or {}
                text = rec.get("text", "")
                facets = rec.get("facets")
                root = rec.get("reply", {}).get("root") or {"uri": n["uri"], "cid": n["cid"]}
                ref = {"uri": n["uri"], "cid": n["cid"], "root": {"uri": root["uri"], "cid": root["cid"]}}
                url = f"https://bsky.app/profile/{a['handle']}/post/{n['uri'].split('/')[-1]}"
                target_did = a.get("did") or (n.get("uri").replace("at://", "").split("/")[0] if n.get("uri") else None)
                if n_post:
                    p_viewer = n_post.get("viewer") or {}
                    n_like = p_viewer.get("like")
                    n_repost = p_viewer.get("repost")
                    if n_like and ref:
                        ref["like_uri"] = n_like
                    if n_repost and ref:
                        ref["repost_uri"] = n_repost
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
                s_a = subject.get("author") or {}
                text = srec.get("text", "")
                facets = srec.get("facets")
                url = f"https://bsky.app/profile/{s_a.get('handle')}/post/{subject['uri'].split('/')[-1]}"
                subj_did = s_a.get("did") or (subj_uri.replace("at://", "").split("/")[0] if subj_uri else None)
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
                s_viewer = subject.get("viewer") or {}
                s_like = s_viewer.get("like")
                s_repost = s_viewer.get("repost")
                target_post = {
                    "author_name": s_a.get("displayName") or s_a.get("handle") or "",
                    "author_handle": "@" + (s_a.get("handle") or ""),
                    "author_avatar": safe_url(s_a.get("avatar")),
                    "author_id": s_a.get("did") or s_a.get("handle") or "",
                    "time": srec.get("createdAt") or subject.get("indexedAt"),
                    "url": url,
                    "uri": subject.get("uri"),
                    "cid": subject.get("cid"),
                    "is_own": bool(self.did and s_a.get("did") == self.did),
                    "liked": bool(s_like),
                    "boosted": bool(s_repost),
                    "likes": subject.get("likeCount", 0),
                    "boosts": subject.get("repostCount", 0),
                    "replies": subject.get("replyCount", 0)
                }
                if not ref and subject.get("uri") and subject.get("cid"):
                    ref = {"uri": subject["uri"], "cid": subject["cid"]}
                if s_like and ref:
                    ref["like_uri"] = s_like
                if s_repost and ref:
                    ref["repost_uri"] = s_repost
            elif subj_uri and kind in ("like", "like_repost", "boost", "boost_repost"):
                post_id = subj_uri.split("/")[-1]
                author_part = subj_uri.replace("at://", "").split("/")[0]
                url = f"https://bsky.app/profile/{author_part}/post/{post_id}"
                text = "(Publicação indisponível)"

            liked = False
            boosted = False
            likes_cnt = 0
            boosts_cnt = 0
            replies_cnt = 0
            if n_post:
                p_viewer = n_post.get("viewer") or {}
                liked = bool(p_viewer.get("like"))
                boosted = bool(p_viewer.get("repost"))
                likes_cnt = n_post.get("likeCount", 0)
                boosts_cnt = n_post.get("repostCount", 0)
                replies_cnt = n_post.get("replyCount", 0)
            elif target_post:
                liked = bool(target_post.get("liked"))
                boosted = bool(target_post.get("boosted"))
                likes_cnt = target_post.get("likes", 0)
                boosts_cnt = target_post.get("boosts", 0)
                replies_cnt = target_post.get("replies", 0)

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
            out.append({"id": n.get("uri") or f"bsky_{n['indexedAt']}_{a.get('did')}",
                        "network": "bluesky", "kind": kind, "name": a.get("displayName") or a["handle"],
                        "handle": "@" + a["handle"], "author_id": a.get("did") or a["handle"],
                        "author_handle": a["handle"], "avatar": safe_url(a.get("avatar")),
                        "html": render_bsky_text(text, facets) if text else "", "time": n["indexedAt"], "url": url, "ref": ref,
                        "media": safe_media_list(media), "quote": quote, "target_post": target_post,
                        "liked": liked, "boosted": boosted, "likes": likes_cnt, "boosts": boosts_cnt, "replies": replies_cnt})
        return out, next_cursor

    def list_conversations(self, limit=30, cursor=None):
        self._ensure()
        params = {"limit": min(max(int(limit), 1), 50)}
        if cursor:
            params["cursor"] = str(cursor)
        res = self.call_chat("GET", "chat.bsky.convo.listConvos", params=params)
        convos = []
        for c in res.get("convos", []):
            cid = c.get("id")
            members = c.get("members") or []
            peer_obj = None
            for m in members:
                if self.did and m.get("did") != self.did:
                    peer_obj = m
                    break
            if not peer_obj and members:
                peer_obj = members[0]
            peer = {
                "id": peer_obj.get("did") if peer_obj else "",
                "name": (peer_obj.get("displayName") or peer_obj.get("handle") or "") if peer_obj else "",
                "handle": ("@" + peer_obj.get("handle")) if peer_obj and peer_obj.get("handle") else "",
                "avatar": safe_url(peer_obj.get("avatar")) if peer_obj else ""
            }
            last_msg = c.get("lastMessage") or {}
            last_text = last_msg.get("text") or ""
            last_time = last_msg.get("sentAt") or ""
            unread_cnt = int(c.get("unreadCount") or 0)
            convos.append({
                "id": cid,
                "network": "bluesky",
                "peer": peer,
                "unread": unread_cnt > 0,
                "unread_count": unread_cnt,
                "last_text": last_text,
                "last_time": last_time,
                "status": c.get("status", "accepted"),
                "muted": bool(c.get("muted"))
            })
        return {"convos": convos, "cursor": res.get("cursor")}

    def get_conversation_messages(self, convo_id, limit=50, cursor=None):
        self._ensure()
        params = {"convoId": convo_id, "limit": min(max(int(limit), 1), 100)}
        if cursor:
            params["cursor"] = str(cursor)
        res = self.call_chat("GET", "chat.bsky.convo.getMessages", params=params)
        raw_msgs = res.get("messages", [])
        messages = []
        for m in raw_msgs:
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            text = m.get("text", "")
            sent_at = m.get("sentAt", "")
            sender = m.get("sender") or {}
            sender_did = sender.get("did") or ""
            is_own = bool(self.did and sender_did == self.did)
            facets = m.get("facets")
            messages.append({
                "id": mid,
                "sender_id": sender_did,
                "is_own": is_own,
                "text": text,
                "html": render_bsky_text(text, facets) if text else "",
                "time": sent_at
            })
        messages.sort(key=lambda x: parse_time(x.get("time")))
        return {
            "id": convo_id,
            "network": "bluesky",
            "messages": messages,
            "cursor": res.get("cursor")
        }

    def send_message(self, convo_id, text):
        self._ensure()
        text = (text or "").strip()
        if not text:
            raise ValueError("O texto da mensagem não pode estar vazio.")
        facets = build_bsky_facets(text, self.resolve_handle)
        msg_payload = {"text": text}
        if facets:
            msg_payload["facets"] = facets
        res = self.call_chat("POST", "chat.bsky.convo.sendMessage", data={
            "convoId": convo_id,
            "message": msg_payload
        })
        sent_at = res.get("sentAt") or now_iso()
        return {
            "id": res.get("id"),
            "sender_id": self.did,
            "is_own": True,
            "text": text,
            "html": render_bsky_text(text, facets) if text else "",
            "time": sent_at
        }

    def mark_as_read(self, convo_id):
        self._ensure()
        return self.call_chat("POST", "chat.bsky.convo.updateRead", data={"convoId": convo_id})

    def start_conversation(self, recipient, text=None):
        self._ensure()
        recipient = (recipient or "").strip()
        if not recipient:
            raise ValueError("Destinatário em falta.")
        m_prof = re.search(r"bsky\.app/profile/([^/?#]+)", recipient)
        target = m_prof.group(1) if m_prof else recipient
        target = target.lstrip("@")
        target_did = target if target.startswith("did:") else self.resolve_handle(target)
        if not target_did:
            raise ApiError(f"Não foi possível encontrar o utilizador {recipient} no Bluesky.")
        res = self.call_chat("GET", "chat.bsky.convo.getConvoForMembers", params={"members": [target_did]})
        convo = res.get("convo") or {}
        convo_id = convo.get("id")
        sent_msg = None
        if text:
            sent_msg = self.send_message(convo_id, text)
        return {
            "convo_id": convo_id,
            "network": "bluesky",
            "message": sent_msg
        }


def sanitize_masto_instance(inst):
    """Normaliza o URL da instância Mastodon, aceitando 'exemplo.social', 'https://exemplo.social',
    e limpando caminhos acidentais colados pelo utilizador (como /@utilizador, /web, /settings, etc.)."""
    inst = (inst or "").strip()
    if not inst:
        return ""
    if not inst.startswith(("http://", "https://")):
        inst = "https://" + inst
    p = urllib.parse.urlparse(inst)
    netloc = p.netloc or p.path.split("/")[0]
    scheme = p.scheme if p.netloc else "https"
    return f"{scheme}://{netloc}".rstrip("/")


class Masto:
    name = "mastodon"

    def __init__(self, c):
        self.base = sanitize_masto_instance(c.get("instance", ""))
        self.token = (c.get("token") or "").strip()
        self.cache = {}  # posts "pai" já obtidos
        self.cache_lock = threading.Lock()  # a cache é usada por várias threads em paralelo
        self.my_id = None
        self.convo_last_status = {}

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
        url = self.base + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
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
        plain_text = ((f"[{x['spoiler_text']}] " if x.get("spoiler_text") else "") + plain(x.get("content"), strip_quote_inline=bool(quote), strip_re=bool(quote))).strip()
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
            "cw": (x.get("spoiler_text") or "").strip(),
            "visibility": x.get("visibility") or "public",
        }
        if name_html:
            out["name_html"] = name_html
        if isinstance(x.get("poll"), dict):
            out["poll"] = self._normalize_poll(x["poll"])
        return out

    @staticmethod
    def _normalize_poll(poll_obj):
        if not isinstance(poll_obj, dict) or not poll_obj.get("id"):
            return None
        opts = []
        for opt in (poll_obj.get("options") or []):
            if isinstance(opt, dict):
                opts.append({
                    "title": str(opt.get("title") or ""),
                    "votes_count": int(opt.get("votes_count") or 0) if opt.get("votes_count") is not None else 0,
                })
        own_votes = [int(v) for v in (poll_obj.get("own_votes") or []) if isinstance(v, int)]
        return {
            "id": str(poll_obj["id"]),
            "expires_at": poll_obj.get("expires_at"),
            "expired": bool(poll_obj.get("expired")),
            "multiple": bool(poll_obj.get("multiple")),
            "votes_count": int(poll_obj.get("votes_count") or 0),
            "voters_count": poll_obj.get("voters_count"),
            "voted": bool(poll_obj.get("voted")),
            "own_votes": own_votes,
            "options": opts,
        }

    def vote_poll(self, poll_id, choices):
        if not poll_id or not re.fullmatch(r"[A-Za-z0-9_-]+", str(poll_id)):
            raise ValueError("ID de sondagem inválido.")
        if not isinstance(choices, list) or not choices or not all(isinstance(c, int) and c >= 0 for c in choices):
            raise ValueError("Opções de voto inválidas.")
        safe_id = urllib.parse.quote(str(poll_id), safe="")
        res = self.call("POST", f"/api/v1/polls/{safe_id}/votes", data={"choices": choices})
        return self._normalize_poll(res)

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

    def get_lists(self):
        r = self.call("GET", "/api/v1/lists")
        out = []
        for item in (r or []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            out.append({
                "id": str(item["id"]),
                "network": "mastodon",
                "name": item.get("title") or "Lista",
                "replies_policy": item.get("replies_policy", "list"),
            })
        out.sort(key=lambda x: x["name"].lower())
        return out

    def list_timeline(self, list_id, cursor=None):
        if not list_id or not re.fullmatch(r"[A-Za-z0-9_-]+", str(list_id)):
            raise ValueError("ID de lista Mastodon inválido.")
        safe_id = urllib.parse.quote(str(list_id), safe="")
        return self._fetch_statuses(f"/api/v1/timelines/list/{safe_id}", cursor=cursor)

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

    @staticmethod
    def _normalize_poll(poll_obj):
        if not isinstance(poll_obj, dict) or not poll_obj.get("id"):
            return None
        opts = []
        for opt in (poll_obj.get("options") or []):
            if isinstance(opt, dict):
                opts.append({
                    "title": str(opt.get("title") or ""),
                    "votes_count": int(opt.get("votes_count") or 0) if opt.get("votes_count") is not None else 0,
                })
        own_votes = [int(v) for v in (poll_obj.get("own_votes") or []) if isinstance(v, int)]
        return {
            "id": str(poll_obj["id"]),
            "expires_at": poll_obj.get("expires_at"),
            "expired": bool(poll_obj.get("expired")),
            "multiple": bool(poll_obj.get("multiple")),
            "votes_count": int(poll_obj.get("votes_count") or 0),
            "voters_count": poll_obj.get("voters_count"),
            "voted": bool(poll_obj.get("voted")),
            "own_votes": own_votes,
            "options": opts,
        }

    def vote_poll(self, poll_id, choices):
        if not poll_id or not re.fullmatch(r"[A-Za-z0-9_-]+", str(poll_id)):
            raise ValueError("ID de sondagem inválido.")
        if not isinstance(choices, list) or not choices or not all(isinstance(c, int) and c >= 0 for c in choices):
            raise ValueError("Opções de voto inválidas.")
        safe_id = urllib.parse.quote(str(poll_id), safe="")
        res = self.call("POST", f"/api/v1/polls/{safe_id}/votes", data={"choices": choices})
        return self._normalize_poll(res)

    def profile(self):
        acc = self.call("GET", "/api/v1/accounts/verify_credentials")
        self.my_id = str(acc.get("id"))
        prof = self._format_acc(acc)
        prof["is_self"] = True
        prof["is_following"] = False
        return prof

    def user_profile(self, actor):
        actor_str = str(actor).strip().lstrip("@")
        if actor_str.startswith("http://") or actor_str.startswith("https://"):
            res = self.call("GET", "/api/v2/search", params={"q": actor_str, "type": "accounts", "resolve": "true"})
            accounts = res.get("accounts") or []
            if accounts:
                acc = accounts[0]
            else:
                raise Exception("Perfil não encontrado.")
        elif actor_str.isdigit():
            acc = self.call("GET", f"/api/v1/accounts/{actor_str}")
        else:
            try:
                acc = self.call("GET", "/api/v1/accounts/lookup", params={"acct": actor_str})
            except Exception:
                res = self.call("GET", "/api/v2/search", params={"q": actor_str, "type": "accounts", "resolve": "true"})
                accounts = res.get("accounts") or []
                if accounts:
                    acc = accounts[0]
                else:
                    raise
        prof = self._format_acc(acc)
        my_id = self.get_my_id()
        acc_id = prof.get("id")
        is_self = (str(acc_id) == str(my_id)) if (my_id and acc_id) else False
        is_following = False
        if not is_self and acc_id:
            try:
                rels = self.call("GET", "/api/v1/accounts/relationships", params={"id[]": [str(acc_id)]})
                if isinstance(rels, list) and len(rels) > 0 and isinstance(rels[0], dict):
                    is_following = bool(rels[0].get("following"))
            except Exception:
                pass
        prof["is_self"] = is_self
        prof["is_following"] = is_following
        return prof

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

    def search(self, q, search_type="all", limit=25):
        clean_q = q.strip()
        if not clean_q:
            return {"posts": [], "actors": [], "hashtags": []}

        type_param = None
        if search_type == "posts":
            type_param = "statuses"
        elif search_type == "actors":
            type_param = "accounts"
        elif search_type == "hashtags":
            type_param = "hashtags"

        params = {"q": clean_q, "limit": min(limit, 40), "resolve": "true"}
        if type_param:
            params["type"] = type_param

        res = self.call("GET", "/api/v2/search", params=params)

        posts = [self.item(st) for st in res.get("statuses", [])]
        actors = [{
            "network": "mastodon",
            "id": str(a.get("id")),
            "name": a.get("display_name") or a.get("username") or "",
            "handle": "@" + (a.get("acct") or a.get("username") or ""),
            "raw_handle": a.get("acct") or a.get("username") or "",
            "avatar": safe_url(a.get("avatar")),
            "description": clean(a.get("note") or ""),
            "url": safe_url(a.get("url"))
        } for a in res.get("accounts", [])]

        hashtags = [{
            "network": "mastodon",
            "name": h.get("name"),
            "url": safe_url(h.get("url")),
            "history": h.get("history")
        } for h in res.get("hashtags", [])]

        return {"posts": posts, "actors": actors, "hashtags": hashtags}

    def thread(self, ref):
        status_id = None
        if isinstance(ref, (str, int)):
            status_id = str(ref)
        elif isinstance(ref, dict):
            status_id = ref.get("id") or ref.get("url")
        if status_id and "/" in str(status_id):
            m = re.search(r"/(\d+)(?:[/?#]|$)", str(status_id))
            if m:
                status_id = m.group(1)
        if not status_id:
            raise RuntimeError("Referência de post inválida para Mastodon.")
        st = self.call("GET", f"/api/v1/statuses/{status_id}")
        c = self.call("GET", f"/api/v1/statuses/{status_id}/context")
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
        if ext == "quicktime":
            ext = "mov"
        data, ctype = multipart_encode({"description": description or ""},
                                       {"file": (f"media.{ext}", raw_bytes, mime)})
        r = http("POST", self.base + "/api/v2/media", data=data, token=self.token,
                 headers={"Content-Type": ctype})
        return r["id"]

    def wait_for_media_processing(self, media_id, max_wait=60):
        """No Mastodon, vídeos necessitam de processamento assíncrono antes da publicação do post."""
        start = time.time()
        while time.time() - start < max_wait:
            try:
                r = http("GET", f"{self.base}/api/v1/media/{media_id}", token=self.token, timeout=10)
                if r.get("url"):
                    return media_id
            except Exception:
                pass
            time.sleep(2)
        return media_id

    def post(self, text, ref=None, images=None, spoiler=None, poll=None, lang=None, visibility=None, quote=None, video=None):
        media_ids = []
        if video and video.get("bytes"):
            mid = self.upload_media(video["bytes"], video.get("mime", "video/mp4"), video.get("alt", ""))
            self.wait_for_media_processing(mid)
            media_ids.append(mid)
        elif images:
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
        return self.call("POST", "/api/v1/statuses", data)

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

    def get_status_source(self, status_id):
        """Obtém o texto fonte (plain) e media_ids de um status próprio no Mastodon."""
        sid = str(status_id or "").strip()
        if not sid:
            raise ApiError("ID de publicação em falta.")
        src = self.call("GET", f"/api/v1/statuses/{sid}/source")
        media_ids = []
        try:
            st = self.call("GET", f"/api/v1/statuses/{sid}")
            media_ids = [str(m["id"]) for m in (st.get("media_attachments") or []) if m.get("id")]
        except Exception:
            pass
        return {
            "text": src.get("text") or "",
            "spoiler_text": src.get("spoiler_text") or "",
            "media_ids": media_ids,
        }

    def edit_status(self, status_id, text, cw="", media_ids=None):
        """Edita um status existente no Mastodon e devolve o item normalizado."""
        sid = str(status_id or "").strip()
        if not sid:
            raise ApiError("ID de publicação em falta.")
        clean_text = (text or "").strip()
        if not clean_text and not media_ids:
            raise ApiError("O texto da publicação não pode estar vazio.")
        data = {
            "status": clean_text,
            "spoiler_text": (cw or "").strip(),
        }
        if media_ids:
            data["media_ids"] = list(media_ids)
        updated = self.call("PUT", f"/api/v1/statuses/{sid}", data)
        return self.item(updated)

    def follow(self, actor):
        acc_id = str(actor).strip().lstrip("@")
        if not acc_id.isdigit():
            prof = self.user_profile(acc_id)
            acc_id = prof.get("id")
        return self.call("POST", f"/api/v1/accounts/{acc_id}/follow")

    def unfollow(self, actor, follow_uri=None):
        acc_id = str(actor).strip().lstrip("@")
        if not acc_id.isdigit():
            prof = self.user_profile(acc_id)
            acc_id = prof.get("id")
        return self.call("POST", f"/api/v1/accounts/{acc_id}/unfollow")

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
            target_post = None
            orig_st = (st.get("reblog") or st) if st else None
            liked = bool(orig_st.get("favourited")) if orig_st else False
            boosted = bool(orig_st.get("reblogged")) if orig_st else False
            likes_cnt = orig_st.get("favourites_count", 0) if orig_st else 0
            boosts_cnt = orig_st.get("reblogs_count", 0) if orig_st else 0
            replies_cnt = orig_st.get("replies_count", 0) if orig_st else 0
            if st:
                st_a = orig_st.get("account") or {}
                my_id = self.get_my_id()
                target_post = {
                    "author_name": st_a.get("display_name") or st_a.get("username") or "",
                    "author_handle": "@" + (st_a.get("acct") or st_a.get("username") or ""),
                    "author_avatar": safe_url(st_a.get("avatar")),
                    "author_id": str(st_a.get("id")),
                    "time": orig_st.get("created_at"),
                    "url": safe_url(orig_st.get("url")),
                    "id": str(orig_st.get("id")),
                    "is_own": bool(my_id and str(st_a.get("id")) == my_id),
                    "liked": liked,
                    "boosted": boosted,
                    "likes": likes_cnt,
                    "boosts": boosts_cnt,
                    "replies": replies_cnt
                }
                if st_a.get("emojis"):
                    target_post["author_name_html"] = render_custom_emojis(html.escape(target_post["author_name"]), st_a.get("emojis"))
            notif_item = {
                "id": str(n.get("id")),
                "network": "mastodon", "kind": kind, "name": a_name,
                "handle": "@" + a.get("acct", ""), "author_id": str(a.get("id")),
                "author_handle": a.get("acct") or a.get("username", ""), "avatar": safe_url(a.get("avatar")),
                "html": notif_html, "time": n.get("created_at"),
                "url": safe_url((st or {}).get("url") or a.get("url")),
                "ref": {"id": orig_st["id"]} if orig_st else None,
                "media": safe_media_list(st_media),
                "quote": st_quote,
                "target_post": target_post,
                "liked": liked,
                "boosted": boosted,
                "likes": likes_cnt,
                "boosts": boosts_cnt,
                "replies": replies_cnt
            }
            if a_name_html:
                notif_item["name_html"] = a_name_html
            out.append(notif_item)
        return out, next_cursor

    def list_conversations(self, limit=30, max_id=None):
        params = {"limit": min(max(int(limit), 1), 40)}
        if max_id:
            params["max_id"] = str(max_id)
        try:
            raw_convos = self.call("GET", "/api/v1/conversations", params=params)
        except Exception as e:
            err_msg = str(e)
            if any(term in err_msg.lower() for term in ("scope", "403", "401")):
                raise ApiError("O teu token do Mastodon não tem permissão para aceder a conversas (escopo read:conversations). Atualiza o teu token nas Definições.")
            raise
        convos = []
        my_id = self.get_my_id()
        for c in (raw_convos or []):
            cid = str(c.get("id"))
            unread = bool(c.get("unread"))
            accounts = c.get("accounts") or []
            peer_acc = None
            for a in accounts:
                if my_id and str(a.get("id")) != str(my_id):
                    peer_acc = a
                    break
            if not peer_acc and accounts:
                peer_acc = accounts[0]
            peer = {
                "id": str(peer_acc.get("id")) if peer_acc else "",
                "name": (peer_acc.get("display_name") or peer_acc.get("username") or "") if peer_acc else "",
                "handle": ("@" + peer_acc.get("acct")) if peer_acc and peer_acc.get("acct") else "",
                "avatar": safe_url(peer_acc.get("avatar")) if peer_acc else ""
            }
            ls = c.get("last_status") or {}
            ls_id = str(ls.get("id")) if ls.get("id") else None
            if ls_id:
                self.convo_last_status[cid] = ls_id
            last_text = preview(plain(ls.get("content", ""))) if ls else ""
            last_time = ls.get("created_at") or ""
            convos.append({
                "id": cid,
                "network": "mastodon",
                "peer": peer,
                "unread": unread,
                "unread_count": 1 if unread else 0,
                "last_text": last_text,
                "last_time": last_time,
                "status": "accepted",
                "last_status_id": ls_id
            })
        return {"convos": convos}

    def get_conversation_messages(self, convo_id, limit=50, last_status_id=None):
        cid = str(convo_id)
        ls_id = last_status_id or self.convo_last_status.get(cid)
        if not ls_id:
            convos = self.list_conversations(limit=40).get("convos", [])
            for c in convos:
                if str(c.get("id")) == cid and c.get("last_status_id"):
                    ls_id = c["last_status_id"]
                    break
        if not ls_id:
            return {"id": convo_id, "network": "mastodon", "messages": []}

        try:
            ctx = self.call("GET", f"/api/v1/statuses/{ls_id}/context")
            ancestors = ctx.get("ancestors") or []
            descendants = ctx.get("descendants") or []
        except Exception:
            ancestors, descendants = [], []

        try:
            last_st = self.call("GET", f"/api/v1/statuses/{ls_id}")
        except Exception:
            last_st = None

        raw_all = ancestors + ([last_st] if last_st else []) + descendants
        seen_ids = set()
        messages = []
        my_id = self.get_my_id()
        for st in raw_all:
            if not isinstance(st, dict):
                continue
            sid = str(st.get("id"))
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            acc = st.get("account") or {}
            sender_id = str(acc.get("id") or "")
            is_own = bool(my_id and sender_id == str(my_id))
            text = plain(st.get("content", ""))
            messages.append({
                "id": sid,
                "sender_id": sender_id,
                "sender_name": acc.get("display_name") or acc.get("username") or "",
                "sender_handle": "@" + acc.get("acct") if acc.get("acct") else "",
                "sender_avatar": safe_url(acc.get("avatar")),
                "is_own": is_own,
                "text": text,
                "html": st.get("content", ""),
                "time": st.get("created_at", "")
            })
        messages.sort(key=lambda x: parse_time(x.get("time")))
        return {
            "id": convo_id,
            "network": "mastodon",
            "messages": messages
        }

    def send_message(self, convo_id, text, recipient=None, last_msg_id=None):
        text = (text or "").strip()
        if not text:
            raise ValueError("O texto da mensagem não pode estar vazio.")
        final_text = text
        if recipient:
            rec_handle = recipient.strip()
            if not rec_handle.startswith("@"):
                rec_handle = "@" + rec_handle
            if rec_handle.lower() not in text.lower():
                final_text = f"{rec_handle} {text}"
        data = {
            "status": final_text,
            "visibility": "direct"
        }
        if last_msg_id:
            data["in_reply_to_id"] = str(last_msg_id)
        elif convo_id and self.convo_last_status.get(str(convo_id)):
            data["in_reply_to_id"] = str(self.convo_last_status[str(convo_id)])
        try:
            st = self.call("POST", "/api/v1/statuses", data=data)
        except Exception as e:
            err_msg = str(e)
            if any(term in err_msg.lower() for term in ("scope", "403", "401")):
                raise ApiError("O teu token do Mastodon não tem permissão para publicar mensagens diretas (escopo write:statuses).")
            raise
        acc = st.get("account") or {}
        st_id = str(st.get("id"))
        if convo_id:
            self.convo_last_status[str(convo_id)] = st_id
        return {
            "id": st_id,
            "sender_id": str(acc.get("id") or ""),
            "sender_name": acc.get("display_name") or acc.get("username") or "",
            "sender_handle": "@" + acc.get("acct") if acc.get("acct") else "",
            "sender_avatar": safe_url(acc.get("avatar")),
            "is_own": True,
            "text": plain(st.get("content", "")),
            "html": st.get("content", ""),
            "time": st.get("created_at") or now_iso()
        }

    def mark_as_read(self, convo_id):
        try:
            return self.call("POST", f"/api/v1/conversations/{convo_id}/read")
        except Exception:
            return {"ok": True}

    def start_conversation(self, recipient, text):
        recipient = (recipient or "").strip()
        if not recipient:
            raise ValueError("Destinatário em falta.")
        text = (text or "").strip()
        if not text:
            raise ValueError("O texto da mensagem não pode estar vazio.")
        m_user = re.search(r"/@([a-zA-Z0-9_.-]+(?:@[a-zA-Z0-9_.-]+)?)", recipient)
        target = ("@" + m_user.group(1)) if m_user else recipient
        if not target.startswith("@"):
            target = "@" + target
        msg = self.send_message(convo_id=None, text=text, recipient=target)
        return {
            "network": "mastodon",
            "message": msg
        }


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
CSP = ("default-src 'none'; manifest-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' https: data: blob:; media-src https: blob:; connect-src 'self' https:; worker-src blob:; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


def clean_alt_text(txt):
    """Limpa o texto alternativo: remove formatação markdown, tópicos, prefixos redundantes e quebras de linha."""
    if not isinstance(txt, str) or not txt.strip():
        return ""
    t = txt.replace("**", "").replace("*", "").replace("`", "").replace("##", "").replace("#", "")
    lines = []
    for line in t.splitlines():
        line = re.sub(r"^\s*[\*\-•\d\.]+\s*", "", line).strip()
        if line:
            lines.append(line)
    t = " ".join(lines).strip()
    for pfx in ("Foto de ", "Imagem de ", "Esta foto mostra ", "Esta imagem mostra ", "Alt text: ", "Alt-text: ", "Alt: ", "Description: "):
        if t.lower().startswith(pfx.lower()):
            t = t[len(pfx):].strip()
            if t:
                t = t[0].upper() + t[1:]
    return t


def generate_alt_text(image_data, lang=None, cfg=None):
    """Gera texto alternativo (alt-text) para uma imagem usando IA (Gemini, Ollama ou OpenAI)."""
    if cfg is None:
        cfg = CFG
    ai_cfg = cfg.get("ai") or {}
    provider = (ai_cfg.get("provider") or "none").lower()
    if provider == "none":
        raise ValueError("O serviço de IA para Alt-Text não está ativado nas Configurações.")

    target_lang = (lang or ai_cfg.get("lang") or "pt-pt").lower().strip()

    if not isinstance(image_data, str) or not image_data.strip():
        raise ValueError("Dados de imagem inválidos ou ausentes.")

    raw = image_data.strip()
    if "," in raw:
        hdr, b64 = raw.split(",", 1)
        mime = hdr.split(";")[0].replace("data:", "") or "image/jpeg"
    else:
        mime = "image/jpeg"
        b64 = raw

    try:
        raw_bytes = base64.b64decode(b64, validate=True)
        if len(raw_bytes) > 20 * 1024 * 1024:
            raise ValueError("Imagem demasiado grande para processamento por IA (máx. 20MB).")
    except (binascii.Error, ValueError) as err:
        raise ValueError(f"Codificação base64 de imagem inválida: {err}")

    if target_lang in ("en", "english"):
        sys_prompt = (
            "You are a web accessibility assistant. Your sole purpose is to generate concise HTML alt-text descriptions for images in English.\n"
            "STRICT RULES:\n"
            "- Write ONLY in English.\n"
            "- Write 1 to 2 clear, continuous sentences in plain text.\n"
            "- Do NOT use bullet points, asterisks, bold, or markdown formatting.\n"
            "- Do not start with 'Image of', 'Photo of', or 'Picture of'.\n"
            "- Accurately transcribe any readable text visible in the image."
        )
        user_prompt = "Describe this image concisely in English for web accessibility alt text."
        prompt = sys_prompt + "\n\n" + user_prompt
    else:
        lang_names = {
            "pt-pt": "português de Portugal",
            "pt-br": "português do Brasil",
            "pt": "português",
            "es": "espanhol",
            "fr": "francês",
        }
        lang_desc = lang_names.get(target_lang, target_lang)
        sys_prompt = (
            f"És um assistente especializado em acessibilidade web. A tua única função é gerar texto alternativo (alt-text) para imagens OBRIGATORIAMENTE em {lang_desc}.\n"
            "REGRAS ESTRITAS:\n"
            f"- Responde EXCLUSIVAMENTE em {lang_desc}. Não uses inglês sob circunstância alguma.\n"
            "- Escreve apenas 1 a 2 frases corridas em texto simples e natural.\n"
            "- NUNCA uses tópicos, listas, asteriscos, negrito nem qualquer formatação Markdown.\n"
            "- Não comeces com 'Foto de', 'Imagem de' ou 'Esta imagem mostra'.\n"
            "- Se a imagem contiver texto visível relevante (rótulos, embalagens, títulos), transcreve-o com precisão."
        )
        user_prompt = f"Descreve esta imagem em {lang_desc} para texto alternativo (alt text) de acessibilidade web."
        prompt = sys_prompt + "\n\n" + user_prompt

    if provider == "gemini":
        key = (ai_cfg.get("gemini_key") or "").strip()
        if not key:
            raise ValueError("A chave de API do Google Gemini não está configurada nas Definições.")
        configured_model = (ai_cfg.get("gemini_model") or "gemini-3.5-flash-lite").strip()
        payload = {
            "system_instruction": {
                "parts": [{"text": sys_prompt}]
            },
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": b64
                            }
                        },
                        {
                            "text": user_prompt
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 800
            }
        }

        # Modelos candidatos em caso de descontinuação, indisponibilidade ou limite de quota por modelo
        models_to_try = [configured_model]
        for fallback_m in (
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-3.5-flash",
            "gemini-3.8-flash",
            "gemini-flash-latest"
        ):
            if fallback_m not in models_to_try:
                models_to_try.append(fallback_m)

        last_err_msg = ""
        res = None
        used_model = configured_model

        for current_model in list(models_to_try):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={key}"
            try:
                res = http("POST", url, data=payload, timeout=60)
                used_model = current_model
                break
            except ApiError as e:
                raw_body = getattr(e, "body", "") or ""
                err_str = str(e)
                clean_msg = err_str

                if "timed out" in err_str.lower():
                    clean_msg = "O pedido ao Google Gemini excedeu o tempo limite (timeout). Tenta novamente."

                # Tentar extrair mensagem do JSON devolvido pela Google API
                for source in (raw_body, err_str.split(": ", 1)[-1] if ": " in err_str else ""):
                    if source:
                        try:
                            parsed_err = json.loads(source)
                            if isinstance(parsed_err, dict) and "error" in parsed_err:
                                err_obj = parsed_err["error"]
                                clean_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
                                break
                        except Exception:
                            pass

                # Se o modelo falhar por argumento inválido ou parâmetro não suportado, retenta com payload simplificado sem generationConfig
                if getattr(e, "status", None) == 400 or "invalid argument" in clean_msg.lower():
                    try:
                        p_simple = {
                            "contents": payload.get("contents", [])
                        }
                        res = http("POST", url, data=p_simple, timeout=60)
                        used_model = current_model
                        break
                    except Exception:
                        pass

                last_err_msg = clean_msg

                # Se a API sugerir explicitamente um modelo alternativo (ex: "Please update your code to use models/gemini-2.5-flash")
                suggested_match = re.search(r"models/([a-zA-Z0-9\.\-_]+)", clean_msg)
                if suggested_match:
                    sugg = suggested_match.group(1)
                    if sugg not in models_to_try:
                        models_to_try.append(sugg)

                # Se for modelo indisponível/descontinuado (404), argumento incompatível (400) ou sobrecarga/alta procura (503, 429)
                is_unavailable_or_busy = (
                    getattr(e, "status", None) in (400, 404, 429, 503)
                    or "404" in err_str
                    or "503" in err_str
                    or "not found" in clean_msg.lower()
                    or "no longer available" in clean_msg.lower()
                    or "deprecated" in clean_msg.lower()
                    or "high demand" in clean_msg.lower()
                    or "overloaded" in clean_msg.lower()
                    or "invalid argument" in clean_msg.lower()
                    or "try again later" in clean_msg.lower()
                    or "resource has been exhausted" in clean_msg.lower()
                )
                if is_unavailable_or_busy:
                    time.sleep(0.5)
                    continue
                else:
                    # Erro fatal de autenticação, chave inválida ou permissão: abortar
                    raise ValueError(f"Erro Gemini API: {clean_msg}")

        if res is None:
            if "high demand" in last_err_msg.lower() or "overloaded" in last_err_msg.lower():
                raise ValueError("Os servidores do Google Gemini estão com tráfego elevado temporário. Aguarda alguns segundos e tenta novamente.")
            if "quota" in last_err_msg.lower() or "resource has been exhausted" in last_err_msg.lower() or "429" in last_err_msg:
                raise ValueError("Limite de quota diária do Google Gemini atingido. Aguarda a renovação da quota ou adiciona uma nova chave gratuita nas Definições.")
            raise ValueError(f"Erro Gemini API: {last_err_msg}")

        # Se mudámos de modelo devido a descontinuação definitiva ou incompatibilidade, guarda nas definições
        if used_model != configured_model and ("no longer available" in last_err_msg.lower() or "deprecated" in last_err_msg.lower() or "not found" in last_err_msg.lower() or "invalid argument" in last_err_msg.lower()):
            try:
                if "ai" in CFG:
                    CFG["ai"]["gemini_model"] = used_model
                    write_config(CFG)
            except Exception:
                pass

        try:
            candidates = res.get("candidates") or []
            if candidates and candidates[0].get("content", {}).get("parts"):
                txt = candidates[0]["content"]["parts"][0].get("text", "").strip()
                cleaned = clean_alt_text(txt)
                if cleaned:
                    return cleaned
        except Exception:
            pass
        if "error" in res:
            err_msg = res["error"].get("message") if isinstance(res["error"], dict) else str(res["error"])
            raise ValueError(f"Erro Gemini API: {err_msg}")
        raise ValueError("A API do Gemini não devolveu texto para esta imagem.")

    elif provider == "ollama":
        base_url = (ai_cfg.get("ollama_url") or "http://localhost:11434").strip().rstrip("/")
        model = (ai_cfg.get("ollama_model") or "llama3.2-vision").strip()
        url = f"{base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [b64],
            "stream": False
        }
        try:
            res = http("POST", url, data=payload, timeout=45)
        except ApiError as e:
            raise ValueError(f"Erro ao ligar ao Ollama ({e}). Verifica se o servidor local está em execução em {base_url}.")

        txt = (res.get("response") or "").strip()
        cleaned = clean_alt_text(txt)
        if cleaned:
            return cleaned
        if "error" in res:
            raise ValueError(f"Erro Ollama: {res['error']}")
        raise ValueError("Ollama não devolveu texto para esta imagem. Verifica se o modelo suporta visão.")

    elif provider in ("openai", "openai_compatible", "compativel"):
        base_url = (ai_cfg.get("openai_url") or "https://api.openai.com/v1").strip().rstrip("/")
        key = (ai_cfg.get("openai_key") or "").strip()
        model = (ai_cfg.get("openai_model") or "gpt-4o-mini").strip()
        url = f"{base_url}/chat/completions"
        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
                    ]
                }
            ],
            "max_tokens": 300
        }
        try:
            res = http("POST", url, data=payload, headers=headers, timeout=30)
        except ApiError as e:
            err_str = str(e)
            clean_msg = err_str
            try:
                if ": " in err_str:
                    _, raw_json = err_str.split(": ", 1)
                    parsed_err = json.loads(raw_json)
                    if isinstance(parsed_err, dict) and "error" in parsed_err:
                        err_obj = parsed_err["error"]
                        clean_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
            except Exception:
                pass
            raise ValueError(f"Erro OpenAI API: {clean_msg}")
        try:
            choices = res.get("choices") or []
            if choices and choices[0].get("message", {}).get("content"):
                txt = choices[0]["message"]["content"].strip()
                cleaned = clean_alt_text(txt)
                if cleaned:
                    return cleaned
        except Exception:
            pass
        if "error" in res:
            err_msg = res["error"].get("message") if isinstance(res["error"], dict) else str(res["error"])
            raise ValueError(f"Erro OpenAI API: {err_msg}")
        raise ValueError("A API compatível não devolveu texto para esta imagem.")

    else:
        raise ValueError(f"Fornecedor de IA desconhecido: '{provider}'.")


def clean_translated_text(txt):
    """Limpa o texto traduzido: remove marcadores markdown externos, aspas e prefixos."""
    if not isinstance(txt, str) or not txt.strip():
        return ""
    t = txt.strip()
    if t.startswith("```") and t.endswith("```"):
        lines = t.splitlines()
        if len(lines) >= 3:
            t = "\n".join(lines[1:-1]).strip()
    for pfx in ("Translation:", "Tradução:", "Translated text:", "Here is the translation:"):
        if t.lower().startswith(pfx.lower()):
            t = t[len(pfx):].strip()
    if (t.startswith('"') and t.endswith('"')) or (t.startswith('“') and t.endswith('”')):
        if t.count('"') == 2 or (t.count('“') == 1 and t.count('”') == 1):
            t = t[1:-1].strip()
    return t


def _call_ai_text(sys_prompt, user_text, cfg=None, temperature=0.2, clean_fn=None):
    """Executa um pedido de geração de texto no fornecedor de IA configurado (Gemini, Ollama ou OpenAI)."""
    if cfg is None:
        cfg = CFG
    ai_cfg = cfg.get("ai") or {}
    provider = (ai_cfg.get("provider") or "none").lower()
    if provider == "none":
        raise ValueError("O serviço de IA não está ativado. Ativa o Google Gemini (gratuito) ou Ollama nas Definições.")
    if not isinstance(user_text, str) or not user_text.strip():
        raise ValueError("Texto em falta ou inválido.")

    post_clean = clean_fn or (lambda s: s.strip())

    if provider == "gemini":
        key = (ai_cfg.get("gemini_key") or "").strip()
        if not key:
            raise ValueError("A chave de API do Google Gemini não está configurada nas Definições.")
        configured_model = (ai_cfg.get("gemini_model") or "gemini-3.5-flash-lite").strip()
        payload = {
            "system_instruction": {"parts": [{"text": sys_prompt}]},
            "contents": [{"parts": [{"text": user_text}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 2000}
        }
        models_to_try = [configured_model]
        for fallback_m in (
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-3.5-flash",
            "gemini-3.8-flash",
            "gemini-flash-latest"
        ):
            if fallback_m not in models_to_try:
                models_to_try.append(fallback_m)

        last_err_msg = ""
        res = None
        used_model = configured_model

        for current_model in list(models_to_try):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={key}"
            try:
                res = http("POST", url, data=payload, timeout=30)
                used_model = current_model
                break
            except ApiError as e:
                raw_body = getattr(e, "body", "") or ""
                err_str = str(e)
                clean_msg = err_str
                if "timed out" in err_str.lower():
                    clean_msg = "O pedido ao Google Gemini excedeu o tempo limite (timeout). Tenta novamente."
                for source in (raw_body, err_str.split(": ", 1)[-1] if ": " in err_str else ""):
                    if source:
                        try:
                            parsed_err = json.loads(source)
                            if isinstance(parsed_err, dict) and "error" in parsed_err:
                                err_obj = parsed_err["error"]
                                clean_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
                                break
                        except Exception:
                            pass
                if getattr(e, "status", None) == 400 or "invalid argument" in clean_msg.lower():
                    try:
                        p_simple = {"contents": [{"parts": [{"text": f"{sys_prompt}\n\n{user_text}"}]}]}
                        res = http("POST", url, data=p_simple, timeout=30)
                        used_model = current_model
                        break
                    except Exception:
                        pass
                last_err_msg = clean_msg
                suggested_match = re.search(r"models/([a-zA-Z0-9\.\-_]+)", clean_msg)
                if suggested_match and suggested_match.group(1) not in models_to_try:
                    models_to_try.append(suggested_match.group(1))
                is_retryable = (
                    getattr(e, "status", None) in (400, 404, 429, 503)
                    or "404" in err_str
                    or "503" in err_str
                    or any(w in clean_msg.lower() for w in (
                        "not found", "no longer available", "deprecated", "high demand",
                        "overloaded", "invalid argument", "try again later", "resource has been exhausted"
                    ))
                )
                if is_retryable:
                    time.sleep(0.5)
                    continue
                raise ValueError(f"Erro Gemini API: {clean_msg}")

        if res is None:
            if "high demand" in last_err_msg.lower() or "overloaded" in last_err_msg.lower():
                raise ValueError("Os servidores do Google Gemini estão com tráfego elevado temporário. Aguarda alguns segundos e tenta novamente.")
            if "quota" in last_err_msg.lower() or "resource has been exhausted" in last_err_msg.lower() or "429" in last_err_msg:
                raise ValueError("Limite de quota diária do Google Gemini atingido. Aguarda a renovação da quota ou adiciona uma nova chave gratuita nas Definições.")
            raise ValueError(f"Erro Gemini API: {last_err_msg}")

        if used_model != configured_model and any(w in last_err_msg.lower() for w in ("no longer available", "deprecated", "not found", "invalid argument")):
            try:
                if "ai" in CFG:
                    CFG["ai"]["gemini_model"] = used_model
                    write_config(CFG)
            except Exception:
                pass

        try:
            candidates = res.get("candidates") or []
            if candidates and candidates[0].get("content", {}).get("parts"):
                txt = candidates[0]["content"]["parts"][0].get("text", "").strip()
                cleaned = post_clean(txt)
                if cleaned:
                    return cleaned
        except Exception:
            pass
        if "error" in res:
            err_msg = res["error"].get("message") if isinstance(res["error"], dict) else str(res["error"])
            raise ValueError(f"Erro Gemini API: {err_msg}")
        raise ValueError("A API do Gemini não devolveu texto traduzido.")

    elif provider == "ollama":
        base_url = (ai_cfg.get("ollama_url") or "http://localhost:11434").strip().rstrip("/")
        model = (ai_cfg.get("ollama_model") or "llama3.2").strip()
        url = f"{base_url}/api/generate"
        payload = {"model": model, "system": sys_prompt, "prompt": user_text, "stream": False}
        try:
            res = http("POST", url, data=payload, timeout=45)
        except ApiError as e:
            raise ValueError(f"Erro ao ligar ao Ollama ({e}). Verifica se o servidor local está em execução em {base_url}.")
        txt = (res.get("response") or "").strip()
        cleaned = post_clean(txt)
        if cleaned:
            return cleaned
        if "error" in res:
            raise ValueError(f"Erro Ollama: {res['error']}")
        raise ValueError("Ollama não devolveu texto para esta tradução.")

    elif provider in ("openai", "openai_compatible", "compativel"):
        base_url = (ai_cfg.get("openai_url") or "https://api.openai.com/v1").strip().rstrip("/")
        key = (ai_cfg.get("openai_key") or "").strip()
        model = (ai_cfg.get("openai_model") or "gpt-4o-mini").strip()
        url = f"{base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_text}
            ],
            "temperature": temperature,
            "max_tokens": 1500
        }
        try:
            res = http("POST", url, data=payload, headers=headers, timeout=30)
        except ApiError as e:
            clean_msg = str(e)
            raw_body = getattr(e, "body", "") or ""
            for source in (raw_body, str(e)):
                if source:
                    try:
                        parsed_err = json.loads(source)
                        if isinstance(parsed_err, dict) and "error" in parsed_err:
                            err_obj = parsed_err["error"]
                            clean_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
                            break
                    except Exception:
                        pass
            raise ValueError(f"Erro OpenAI API: {clean_msg}")
        try:
            choices = res.get("choices") or []
            if choices and choices[0].get("message", {}).get("content"):
                txt = choices[0]["message"]["content"].strip()
                cleaned = post_clean(txt)
                if cleaned:
                    return cleaned
        except Exception:
            pass
        if "error" in res:
            err_msg = res["error"].get("message") if isinstance(res["error"], dict) else str(res["error"])
            raise ValueError(f"Erro OpenAI API: {err_msg}")
        raise ValueError("A API compatível não devolveu texto traduzido.")

    else:
        raise ValueError(f"Fornecedor de IA desconhecido: '{provider}'.")


def translate_text(text, target_lang=None, cfg=None):
    """Traduz o texto de uma publicação social usando o fornecedor de IA configurado (Gemini, Ollama ou OpenAI)."""
    if cfg is None:
        cfg = CFG
    ai_cfg = cfg.get("ai") or {}
    provider = (ai_cfg.get("provider") or "none").lower()
    if provider == "none":
        raise ValueError("O serviço de IA não está ativado. Ativa o Google Gemini (gratuito) ou Ollama nas Definições para traduzir publicações.")

    if not isinstance(text, str) or not text.strip():
        raise ValueError("Texto para tradução em falta ou inválido.")

    target_lang = (target_lang or ai_cfg.get("lang") or "pt").lower().strip()
    lang_name_en = {
        "pt": "Portuguese (Portugal)",
        "pt-pt": "Portuguese (Portugal)",
        "pt-br": "Portuguese (Brazil)",
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German"
    }
    target_desc = lang_name_en.get(target_lang, "Portuguese")
    sys_prompt = (
        f"You are a professional social media translator for Bluesky and Mastodon.\n"
        f"Translate the following user post accurately into {target_desc}.\n"
        "STRICT RULES:\n"
        f"- Output ONLY the direct translated text in {target_desc}, nothing else.\n"
        "- Do NOT add quotation marks around the entire translation.\n"
        "- Do NOT add any intro, preamble, explanations, or notes.\n"
        "- Preserve all @mentions (e.g. @user.bsky.social), #hashtags, URLs, emojis, and line breaks exactly as in the original.\n"
        "- Maintain the natural, informal tone suitable for social media posts."
    )
    return _call_ai_text(sys_prompt, text, cfg=cfg, temperature=0.2, clean_fn=clean_translated_text)


def summarize_catchup_posts(posts, hours=12, target_lang=None, cfg=None):
    """Gera um resumo estruturado por tópicos dos destaques recentes da Timeline."""
    if not isinstance(posts, list) or not posts:
        raise ValueError("Não há publicações suficientes para resumir.")
    if cfg is None:
        cfg = CFG
    ai_cfg = cfg.get("ai") or {}
    target_lang = (target_lang or ai_cfg.get("lang") or "pt").lower().strip()
    lang_desc = "English" if target_lang.startswith("en") else "Portuguese (Portugal)"
    lines = []
    for idx, p in enumerate(posts[:25]):
        if not isinstance(p, dict):
            continue
        author = str(p.get("author") or p.get("handle") or "User").strip()
        net = str(p.get("network") or "").strip()
        txt = str(p.get("text") or "").strip().replace("\n", " ")
        if txt:
            lines.append(f"{idx+1}. [{net}] {author}: {txt[:280]}")
    if not lines:
        raise ValueError("As publicações selecionadas não contêm texto para resumir.")
    sys_prompt = (
        f"You are summarizing a user's unified Bluesky + Mastodon timeline from the last {hours} hours in {lang_desc}.\n"
        "Create a concise, friendly 'Catch-Up' digest grouped into 3 to 5 bullet points highlighting the main topics, discussions, and noteworthy posts.\n"
        "Mention key authors (@handle or name) when relevant. Do NOT invent anything outside the provided posts."
    )
    return _call_ai_text(sys_prompt, "\n".join(lines), cfg=cfg, temperature=0.3)


_TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def _extra_allowed_hosts():
    raw = os.environ.get("MASTOSKY_ALLOWED_HOSTS", "")
    return {h.strip().lower().rstrip(".") for h in raw.split(",") if h.strip()}


def is_private_or_local_host(host_str):
    """Verifica se o host é local ou pertence a gamas privadas (RFC 1918 / RFC 4193 / Tailscale CGNAT / link-local / .local / .ts.net)."""
    if not host_str:
        return False
    host = host_str.strip()
    if host.startswith("[") and "]" in host:
        host = host[1:host.index("]")]
    elif host.count(":") == 1:
        host = host.split(":")[0]
    host = host.lower().rstrip(".")
    if not host:
        return False
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    if host.endswith(".local") or (host.endswith(".ts.net") and len(host) > 7):
        return True
    if host in _extra_allowed_hosts():
        return True
    try:
        if host == socket.gethostname().lower():
            return True
    except Exception:
        pass
    try:
        ip = ipaddress.ip_address(host)
        if ip in _TAILSCALE_NET:
            return True
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None and (mapped in _TAILSCALE_NET or mapped.is_private or mapped.is_loopback or mapped.is_link_local):
            return True
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def get_tailscale_ip():
    """Deteta o IP ou hostname Tailscale desta máquina (100.64.0.0/10 ou MASTOSKY_TAILSCALE_HOST)."""
    env_host = os.environ.get("MASTOSKY_TAILSCALE_HOST", "").strip()
    if env_host:
        return env_host
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("100.100.100.100", 53))
            ip_str = s.getsockname()[0]
        finally:
            s.close()
        if ipaddress.ip_address(ip_str) in _TAILSCALE_NET:
            return ip_str
    except Exception:
        pass
    return None


def get_tailscale_url(port=None):
    """Constrói o URL Tailscale se disponível (MASTOSKY_TAILSCALE_URL, MASTOSKY_TAILSCALE_HOST ou IP 100.64.0.0/10)."""
    env_url = os.environ.get("MASTOSKY_TAILSCALE_URL", "").strip().rstrip("/")
    if env_url:
        return env_url
    ts = get_tailscale_ip()
    if not ts:
        return None
    if ts.startswith(("http://", "https://")):
        return ts.rstrip("/")
    return f"http://{ts}:{port or PORT}"


def get_local_ip():
    """Deteta o endereço IP local na rede (Wi-Fi/LAN) sem tráfego externo."""
    for target in ("10.255.255.255", "192.168.255.255", "8.8.8.8"):
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((target, 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass

    if sys.platform == "darwin":
        for iface in ("en0", "en1", "en2"):
            try:
                out = subprocess.check_output(["ipconfig", "getifaddr", iface], text=True, stderr=subprocess.DEVNULL).strip()
                if out and not out.startswith("127."):
                    return out
            except Exception:
                pass

    if sys.platform.startswith("linux"):
        try:
            out = subprocess.check_output(["hostname", "-I"], text=True, stderr=subprocess.DEVNULL).split()
            for ip in out:
                if not ip.startswith("127."):
                    return ip
        except Exception:
            pass

    try:
        hname = socket.gethostname()
        ip = socket.gethostbyname(hname)
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    return "127.0.0.1"


def generate_qr_matrix(text, level='M'):
    """Gera matriz booleana de QR Code para URLs curtas (Byte Mode, v1-6). Zero dependências externas."""
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        exp[i + 255] = x
        log[x] = i
        x = (x << 1) ^ (0x11d if (x & 0x80) else 0)

    def gf_mul(a, b):
        return 0 if a == 0 or b == 0 else exp[log[a] + log[b]]

    def rs_gen_poly(num_ec):
        poly = [1]
        for i in range(num_ec):
            next_poly = [0] * (len(poly) + 1)
            factor = exp[i]
            for j in range(len(poly)):
                next_poly[j] ^= poly[j]
                next_poly[j + 1] ^= gf_mul(poly[j], factor)
            poly = next_poly
        return poly

    def rs_encode(data, num_ec):
        gen = rs_gen_poly(num_ec)
        res = [0] * num_ec
        for d in data:
            factor = d ^ res[0]
            for j in range(num_ec - 1):
                res[j] = res[j + 1] ^ gf_mul(gen[j + 1], factor)
            res[num_ec - 1] = gf_mul(gen[num_ec], factor)
        return res

    VERSIONS = [
        None,
        {"total": 26, "dcL": 19, "dcM": 16, "ecL": 7, "ecM": 10, "blocksL": 1, "blocksM": 1, "align": []},
        {"total": 44, "dcL": 34, "dcM": 28, "ecL": 10, "ecM": 16, "blocksL": 1, "blocksM": 1, "align": [6, 18]},
        {"total": 70, "dcL": 55, "dcM": 44, "ecL": 15, "ecM": 26, "blocksL": 1, "blocksM": 1, "align": [6, 22]},
        {"total": 100, "dcL": 80, "dcM": 64, "ecL": 20, "ecM": 36, "blocksL": 1, "blocksM": 2, "align": [6, 26]},
        {"total": 134, "dcL": 108, "dcM": 86, "ecL": 26, "ecM": 48, "blocksL": 1, "blocksM": 2, "align": [6, 30]},
        {"total": 172, "dcL": 136, "dcM": 108, "ecL": 36, "ecM": 64, "blocksL": 2, "blocksM": 4, "align": [6, 34]},
    ]

    utf8 = list(text.encode("utf-8"))
    v = 1
    for ver in range(1, 7):
        cap = VERSIONS[ver]["dcL" if level == 'L' else "dcM"]
        if len(utf8) + 2 <= cap:
            v = ver
            break
    vinfo = VERSIONS[v]
    data_cap = vinfo["dcL" if level == 'L' else "dcM"]

    bits = []
    def put_bits(num, count):
        for i in range(count - 1, -1, -1):
            bits.append((num >> i) & 1)

    put_bits(4, 4)
    put_bits(len(utf8), 8)
    for b in utf8:
        put_bits(b, 8)
    term_len = min(4, data_cap * 8 - len(bits))
    bits.extend([0] * term_len)
    while len(bits) % 8 != 0:
        bits.append(0)

    bytes_data = []
    for i in range(0, len(bits), 8):
        val = 0
        for j in range(8):
            val = (val << 1) | bits[i + j]
        bytes_data.append(val)

    pad = 0xEC
    while len(bytes_data) < data_cap:
        bytes_data.append(pad)
        pad = 0x11 if pad == 0xEC else 0xEC

    num_blocks = vinfo["blocksL" if level == 'L' else "blocksM"]
    total_ec = vinfo["ecL" if level == 'L' else "ecM"]
    ec_per_block = total_ec // num_blocks
    total_dc = data_cap

    blocks = []
    ec_blocks = []
    base_dc_len = total_dc // num_blocks
    num_large_blocks = total_dc % num_blocks
    offset = 0

    for b in range(num_blocks):
        dc_len = base_dc_len + (1 if b >= (num_blocks - num_large_blocks) else 0)
        blk = bytes_data[offset:offset + dc_len]
        offset += dc_len
        blocks.append(blk)
        ec_blocks.append(rs_encode(blk, ec_per_block))

    final_bytes = []
    max_dc = base_dc_len + 1
    for i in range(max_dc):
        for b in range(num_blocks):
            if i < len(blocks[b]):
                final_bytes.append(blocks[b][i])
    for i in range(ec_per_block):
        for b in range(num_blocks):
            final_bytes.append(ec_blocks[b][i])

    size = 17 + 4 * v
    matrix = [[False] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def set_finder(row, col):
        for r in range(-1, 8):
            for c in range(-1, 8):
                cr, cc = row + r, col + c
                if 0 <= cr < size and 0 <= cc < size:
                    val = (0 <= r <= 6 and 0 <= c <= 6) and (
                        r == 0 or r == 6 or c == 0 or c == 6 or (2 <= r <= 4 and 2 <= c <= 4)
                    )
                    matrix[cr][cc] = val
                    reserved[cr][cc] = True

    set_finder(0, 0)
    set_finder(0, size - 7)
    set_finder(size - 7, 0)

    for i in range(8, size - 8):
        if not reserved[6][i]:
            matrix[6][i] = (i % 2 == 0)
            reserved[6][i] = True
        if not reserved[i][6]:
            matrix[i][6] = (i % 2 == 0)
            reserved[i][6] = True

    for ar in vinfo["align"]:
        for ac in vinfo["align"]:
            if reserved[ar][ac]:
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    val = (abs(r) == 2 or abs(c) == 2 or (r == 0 and c == 0))
                    matrix[ar + r][ac + c] = val
                    reserved[ar + r][ac + c] = True

    for i in range(9):
        if i < size:
            reserved[8][i] = True
            reserved[i][8] = True
        if size - 1 - i >= 0:
            reserved[8][size - 1 - i] = True
            reserved[size - 1 - i][8] = True
    matrix[size - 8][8] = True
    reserved[size - 8][8] = True

    all_bits = []
    for b in final_bytes:
        for shift in range(7, -1, -1):
            all_bits.append((b >> shift) & 1)

    remainder = 7 if (2 <= v <= 6) else 0
    all_bits.extend([0] * remainder)

    bit_idx = 0
    dir_y = -1
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        for i in range(size):
            r = (size - 1 - i) if dir_y == -1 else i
            for c in range(2):
                curr_col = col - c
                if not reserved[r][curr_col]:
                    bit = all_bits[bit_idx] if bit_idx < len(all_bits) else 0
                    bit_idx += 1
                    mask = ((r + curr_col) % 2 == 0)
                    matrix[r][curr_col] = bool(bit ^ (1 if mask else 0))
        col -= 2
        dir_y = -dir_y

    format_data = (1 if level == 'L' else 0) << 3
    bch = format_data << 10
    gen_bch = 0x537
    for i in range(4, -1, -1):
        if (bch >> (i + 10)) & 1:
            bch ^= (gen_bch << i)
    full_format = ((format_data << 10) | bch) ^ 0x5412

    for i in range(15):
        bit = bool((full_format >> i) & 1)
        if i < 6:
            matrix[8][i] = bit
        elif i == 6:
            matrix[8][7] = bit
        elif i == 7:
            matrix[8][8] = bit
        elif i == 8:
            matrix[7][8] = bit
        else:
            matrix[14 - i][8] = bit

        if i < 8:
            matrix[size - 1 - i][8] = bit
        else:
            matrix[8][size - 15 + i] = bit

    return matrix


def qr_to_ascii(matrix, margin=1):
    """Converte matriz booleana num bloco de texto ANSI Unicode compacto."""
    size = len(matrix)
    full_size = size + margin * 2
    grid = [[False] * full_size for _ in range(full_size)]
    for r in range(size):
        for c in range(size):
            grid[r + margin][c + margin] = matrix[r][c]

    lines = []
    for r in range(0, full_size, 2):
        row_str = "  "
        for c in range(full_size):
            top = grid[r][c]
            bot = grid[r + 1][c] if r + 1 < full_size else False
            if top and bot:
                row_str += "█"
            elif top and not bot:
                row_str += "▀"
            elif not top and bot:
                row_str += "▄"
            else:
                row_str += " "
        lines.append(row_str)
    return "\n".join(lines)


def qr_to_svg(matrix, margin=3):
    """Converte matriz booleana num SVG escalável para o navegador."""
    size = len(matrix)
    total_size = size + margin * 2
    path = []
    for r in range(size):
        for c in range(size):
            if matrix[r][c]:
                path.append(f"M{c + margin},{r + margin}h1v1h-1z")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_size} {total_size}" shape-rendering="crispEdges">'
        f'<rect width="100%" height="100%" fill="#ffffff" rx="10"/>'
        f'<path d="{"".join(path)}" fill="#0B1020"/>'
        '</svg>'
    )


class H(BaseHTTPRequestHandler):
    verbose = False

    def log_message(self, *a):
        if self.verbose:
            super().log_message(*a)

    def allowed(self):
        # Protege contra outros sites a falarem com o servidor local.
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")

        if not LAN_MODE:
            ok = (f"127.0.0.1:{PORT}", f"localhost:{PORT}")
            return host in ok and (origin is None or origin in [f"http://{h}" for h in ok])

        if not host:
            return False

        host_parts = host.rsplit(":", 1)
        if len(host_parts) == 2 and host_parts[1].isdigit():
            if int(host_parts[1]) != PORT:
                return False

        if not is_private_or_local_host(host):
            return False

        if origin is not None:
            try:
                parsed_origin = urllib.parse.urlparse(origin)
                if parsed_origin.scheme not in ("http", "https"):
                    return False
                if parsed_origin.port and parsed_origin.port != PORT:
                    return False
                if not is_private_or_local_host(parsed_origin.hostname):
                    return False
            except Exception:
                return False

        return True

    def send(self, code, body, ctype="application/json", precompressed_gz=None, extra_headers=None):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        compressible = (
            ctype.startswith("text/")
            or ctype in ("application/json", "application/javascript", "image/svg+xml", "application/manifest+json")
        )
        accept_enc = (self.headers.get("Accept-Encoding") or "").lower()
        use_gzip = compressible and "gzip" in accept_enc and (precompressed_gz is not None or len(b) >= 1024)
        if use_gzip:
            if precompressed_gz is not None:
                b = precompressed_gz
            else:
                comp = zlib.compressobj(level=6, wbits=16 + zlib.MAX_WBITS)
                b = comp.compress(b) + comp.flush()
        self.send_response(code)
        ct_header = ctype if (ctype.startswith("image/") and ctype != "image/svg+xml") or ctype == "application/octet-stream" else (ctype + "; charset=utf-8")
        self.send_header("Content-Type", ct_header)
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", CSP)
        if extra_headers:
            for hk, hv in extra_headers.items():
                self.send_header(hk, hv)
        if ctype.startswith("image/"):
            self.send_header("Cache-Control", "public, max-age=86400")
        elif "text/html" in ctype:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(b)

    def do_OPTIONS(self):
        if not self.allowed():
            return self.send(403, {"error": "forbidden"})
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CSRF-Token")
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not self.allowed():
            return self.send(403, {"error": "forbidden"})
        if path in ("/", "/index.html"):
            index_path = DIR / "index.html"
            mtime_ns = index_path.stat().st_mtime_ns
            with _INDEX_CACHE_LOCK:
                if (
                    _INDEX_HTML_CACHE["mtime_ns"] == mtime_ns
                    and _INDEX_HTML_CACHE["token"] == SESSION_TOKEN
                    and _INDEX_HTML_CACHE["bytes"] is not None
                ):
                    raw_b = _INDEX_HTML_CACHE["bytes"]
                    gz_b = _INDEX_HTML_CACHE["gz"]
                else:
                    html_text = index_path.read_text(encoding="utf-8")
                    if '<meta name="csrf-token"' in html_text:
                        html_text = re.sub(r'<meta name="csrf-token" content="[^"]*">', f'<meta name="csrf-token" content="{SESSION_TOKEN}">', html_text)
                    else:
                        html_text = html_text.replace("</head>", f'<meta name="csrf-token" content="{SESSION_TOKEN}">\n</head>', 1)
                    raw_b = html_text.encode("utf-8")
                    comp = zlib.compressobj(level=6, wbits=16 + zlib.MAX_WBITS)
                    gz_b = comp.compress(raw_b) + comp.flush()
                    _INDEX_HTML_CACHE.update({"mtime_ns": mtime_ns, "token": SESSION_TOKEN, "bytes": raw_b, "gz": gz_b})
            return self.send(200, raw_b, "text/html", precompressed_gz=gz_b)
        if path == "/api/csrf":
            return self.send(200, {"token": SESSION_TOKEN})
        if path == "/api/version":
            qs = urllib.parse.parse_qs(parsed.query)
            force = qs.get("force", ["0"])[0] == "1"
            return self.send(200, check_github_update(force=force))
        if path in ("/app.css", "/app.js"):
            asset_path = DIR / path.lstrip("/")
            if asset_path.is_file():
                ctype = "text/css" if path.endswith(".css") else "application/javascript"
                mtime_ns = asset_path.stat().st_mtime_ns
                etag = f'"{mtime_ns:x}"'
                if (self.headers.get("If-None-Match") or "").strip() == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                with _INDEX_CACHE_LOCK:
                    cached = _STATIC_ASSET_CACHE.get(path)
                    if cached and cached["mtime_ns"] == mtime_ns and cached["bytes"] is not None:
                        raw_b = cached["bytes"]
                        gz_b = cached["gz"]
                    else:
                        raw_b = asset_path.read_bytes()
                        comp = zlib.compressobj(level=6, wbits=16 + zlib.MAX_WBITS)
                        gz_b = comp.compress(raw_b) + comp.flush()
                        _STATIC_ASSET_CACHE[path] = {"mtime_ns": mtime_ns, "bytes": raw_b, "gz": gz_b}
                return self.send(
                    200, raw_b, ctype, precompressed_gz=gz_b,
                    extra_headers={"ETag": etag, "Cache-Control": "no-cache"}
                )
        if path in ("/manifest.json", "/manifest.webmanifest"):
            mpath = DIR / "manifest.json"
            if mpath.is_file():
                return self.send(200, mpath.read_bytes(), "application/manifest+json")
        if path == "/sw.js":
            sw_code = (
                f'const CACHE_NAME = "mastosky-v{VERSION}";\n'
                'const PRECACHE = ["/manifest.json", "/vendor/hls.min.js", "/brand/favicon.svg"];\n'
                'const NETWORK_FIRST_APIS = ["/api/timeline", "/api/notifications", "/api/explore", "/api/lists", "/api/list_feed", "/api/status"];\n'
                'self.addEventListener("install", (e) => {\n'
                '  self.skipWaiting();\n'
                '  e.waitUntil(caches.open(CACHE_NAME).then((c) => c.addAll(PRECACHE)).catch(() => {}));\n'
                '});\n'
                'self.addEventListener("activate", (e) => {\n'
                '  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))).then(() => self.clients.claim()));\n'
                '});\n'
                'self.addEventListener("fetch", (e) => {\n'
                '  if (e.request.method !== "GET") return;\n'
                '  const url = new URL(e.request.url);\n'
                '  if (url.origin !== self.location.origin) return;\n'
                '  if (url.pathname.startsWith("/brand/") || url.pathname.startsWith("/vendor/") || url.pathname === "/manifest.json") {\n'
                '    e.respondWith(caches.match(e.request).then((cached) => cached || fetch(e.request).then((res) => {\n'
                '      if (res && res.ok) { const copy = res.clone(); caches.open(CACHE_NAME).then((c) => c.put(e.request, copy)); }\n'
                '      return res;\n'
                '    })));\n'
                '    return;\n'
                '  }\n'
                '  if (url.pathname === "/" || url.pathname === "/index.html" || url.pathname === "/app.css" || url.pathname === "/app.js" || NETWORK_FIRST_APIS.includes(url.pathname)) {\n'
                '    e.respondWith(fetch(e.request).then((res) => {\n'
                '      if (res && res.ok) { const copy = res.clone(); caches.open(CACHE_NAME).then((c) => c.put(e.request, copy)); }\n'
                '      return res;\n'
                '    }).catch(() => caches.match(e.request)));\n'
                '  }\n'
                '});\n'
            )
            return self.send(200, sw_code.encode("utf-8"), "application/javascript")
        if path == "/api/lan":
            local_ip = get_local_ip()
            lan_url = f"http://{local_ip}:{PORT}"
            hname = socket.gethostname()
            mdns_url = f"http://{hname}.local:{PORT}" if hname and not hname.endswith(".local") else f"http://{hname}:{PORT}"
            try:
                mat = generate_qr_matrix(lan_url, level='M')
                svg = qr_to_svg(mat, margin=3)
            except Exception:
                svg = ""
            ts_ip = get_tailscale_ip()
            ts_url = get_tailscale_url(PORT)
            ts_svg = ""
            if ts_url:
                try:
                    ts_mat = generate_qr_matrix(ts_url, level='M')
                    ts_svg = qr_to_svg(ts_mat, margin=3)
                except Exception:
                    ts_svg = ""
            return self.send(200, {
                "lan": LAN_MODE,
                "host": LISTEN_HOST,
                "port": PORT,
                "local_ip": local_ip,
                "url": lan_url,
                "mdns_url": mdns_url,
                "hostname": hname,
                "qr_svg": svg,
                "tailscale_ip": ts_ip,
                "tailscale_url": ts_url,
                "tailscale_qr_svg": ts_svg
            })
        if path == "/api/user_data":
            return self.send(200, {"ok": True, "data": load_user_data()})
        if path == "/api/scheduled":
            items = load_scheduled_posts()
            items.sort(key=lambda it: (0 if it.get("status") in ("pending", "missed", "partial", "failed") else 1, int(it.get("scheduled_at") or 0)))
            return self.send(200, {"ok": True, "items": items, "now": int(time.time())})
        if path == "/vendor/hls.min.js":
            return self.send(200, (DIR / "vendor" / "hls.min.js").read_bytes(), "application/javascript")
        if path.startswith("/brand/"):
            rel = path[7:]
            target = (DIR / "brand" / rel).resolve()
            if target.is_file() and str(target).startswith(str((DIR / "brand").resolve())):
                if path.endswith(".svg"):
                    mime = "image/svg+xml"
                elif path.endswith(".png"):
                    mime = "image/png"
                elif path.endswith(".css"):
                    mime = "text/css"
                else:
                    mime = "application/octet-stream"
                return self.send(200, target.read_bytes(), mime)
        if path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
            ati = DIR / "brand" / "apple-touch-icon.png"
            if ati.is_file():
                return self.send(200, ati.read_bytes(), "image/png")
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
        if path == "/api/link_preview":
            qs = urllib.parse.parse_qs(parsed.query)
            target_url = qs.get("url", [None])[0]
            if not target_url:
                return self.send(400, {"ok": False, "error": "Parâmetro url em falta."})
            try:
                return self.send(200, fetch_link_preview(target_url))
            except Exception as e:
                return self.send(400, {"ok": False, "error": str(e)})
        if path == "/api/reader":
            qs = urllib.parse.parse_qs(parsed.query)
            target_url = qs.get("url", [None])[0]
            if not target_url:
                return self.send(400, {"ok": False, "error": "Parâmetro url em falta."})
            try:
                return self.send(200, fetch_article_reader(target_url))
            except Exception as e:
                return self.send(400, {"ok": False, "error": str(e)})
        if path == "/api/post_source":
            qs = urllib.parse.parse_qs(parsed.query)
            net = (qs.get("network", ["mastodon"])[0] or "").strip().lower()
            sid = (qs.get("id", [""])[0] or "").strip()
            if net != "mastodon" or net not in CLIENTS:
                return self.send(400, {"ok": False, "error": "Fonte apenas disponível para Mastodon configurado."})
            try:
                src = CLIENTS[net].get_status_source(sid)
                return self.send(200, {"ok": True, **src})
            except Exception as e:
                return self.send(400, {"ok": False, "error": str(e)})
        if path == "/api/local_image":
            qs = urllib.parse.parse_qs(parsed.query)
            target_path = qs.get("path", [None])[0]
            if not target_path:
                return self.send(400, {"error": "Parâmetro path em falta."})
            p = Path(target_path).expanduser().resolve()
            home = Path.home().resolve()
            if not (p.is_file() and (str(p).startswith(str(home)) or str(p).startswith(str(DIR.resolve())))):
                return self.send(403, {"error": "Acesso a ficheiro não permitido."})
            valid_exts = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
                ".bmp": "image/bmp",
                ".svg": "image/svg+xml",
                ".avif": "image/avif"
            }
            ext = p.suffix.lower()
            if ext not in valid_exts:
                return self.send(400, {"error": "Extensão de imagem inválida."})
            if p.stat().st_size > 15 * 1024 * 1024:
                return self.send(400, {"error": "Ficheiro demasiado grande (máx 15MB)."})
            return self.send(200, p.read_bytes(), valid_exts[ext])
        if path == "/api/status":
            ai_cfg = CFG.get("ai", {})
            ai_data = {
                "provider": ai_cfg.get("provider", "none"),
                "lang": ai_cfg.get("lang", "pt-pt"),
                "auto": ai_cfg.get("auto", False),
                "gemini_key": "",
                "has_gemini_key": bool((ai_cfg.get("gemini_key") or "").strip()),
                "gemini_model": ai_cfg.get("gemini_model", "gemini-3.5-flash-lite"),
                "ollama_url": ai_cfg.get("ollama_url", "http://localhost:11434"),
                "ollama_model": ai_cfg.get("ollama_model", "llama3.2-vision"),
                "openai_url": ai_cfg.get("openai_url", "https://api.openai.com/v1"),
                "openai_key": "",
                "has_openai_key": bool((ai_cfg.get("openai_key") or "").strip()),
                "openai_model": ai_cfg.get("openai_model", "gpt-4o-mini"),
            }
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
                },
                "ai": ai_data
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
            for name, its, nxt, err in _API_EXECUTOR.map(get, active_clients):
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
        if path == "/api/lists":
            if not CLIENTS:
                return self.send(200, {"items": [], "errors": {}, "networks": []})
            qs = urllib.parse.parse_qs(parsed.query)
            target_net = qs.get("network", [None])[0]
            active_clients = [c for c in CLIENTS.values() if not target_net or c.name == target_net]

            def fetch_lists(c):
                try:
                    if c.name == "bluesky":
                        return c.name, c.get_custom_feeds(), None
                    if c.name == "mastodon":
                        return c.name, c.get_lists(), None
                    return c.name, [], None
                except Exception as e:
                    return c.name, [], str(e)

            all_lists, errors = [], {}
            for name, lst, err in _API_EXECUTOR.map(fetch_lists, active_clients):
                all_lists.extend(lst)
                if err:
                    errors[name] = err
            return self.send(200, {"items": all_lists, "errors": errors, "networks": list(CLIENTS)})
        if path == "/api/list_feed":
            qs = urllib.parse.parse_qs(parsed.query)
            net = qs.get("network", [""])[0].strip().lower()
            feed_id = qs.get("id", [""])[0].strip()
            cursor = qs.get("cursor", [None])[0]
            if net not in ("bluesky", "mastodon") or not feed_id:
                return self.send(400, {"error": "Parâmetros inválidos (network e id são obrigatórios)."})
            client = CLIENTS.get(net)
            if not client:
                return self.send(400, {"error": f"Rede {net} não configurada."})
            try:
                if net == "bluesky":
                    its, nxt = client.custom_feed(feed_id, cursor=cursor)
                else:
                    its, nxt = client.list_timeline(feed_id, cursor=cursor)
                return self.send(200, {"items": its, "cursor": nxt, "network": net, "id": feed_id})
            except ValueError as ve:
                return self.send(400, {"error": str(ve)})
            except Exception as e:
                return self.send(500, {"error": str(e)})
        if path == "/api/search":
            if not CLIENTS:
                return self.send(200, {"posts": [], "actors": [], "hashtags": [], "errors": {}})
            qs = urllib.parse.parse_qs(parsed.query)
            q = qs.get("q", [""])[0].strip()
            if not q:
                return self.send(200, {"posts": [], "actors": [], "hashtags": [], "errors": {}})
            search_type = qs.get("type", ["all"])[0].strip().lower()
            if search_type not in ("all", "posts", "actors", "hashtags"):
                search_type = "all"
            target_net = qs.get("network", [None])[0]
            try:
                limit = int(qs.get("limit", [25])[0])
            except (ValueError, TypeError):
                limit = 25
            limit = max(1, min(limit, 50))

            active_clients = [c for c in CLIENTS.values() if not target_net or c.name == target_net]
            all_posts = []
            all_actors = []
            all_hashtags = []
            errors = {}

            def do_search(c):
                try:
                    res = c.search(q, search_type=search_type, limit=limit)
                    return c.name, res, None
                except Exception as e:
                    return c.name, None, str(e)

            for name, res, err in _API_EXECUTOR.map(do_search, active_clients):
                if err:
                    errors[name] = err
                elif res:
                    all_posts.extend(res.get("posts", []))
                    all_actors.extend(res.get("actors", []))
                    all_hashtags.extend(res.get("hashtags", []))

            all_posts.sort(key=lambda x: x.get("time") or "", reverse=True)

            return self.send(200, {
                "posts": all_posts,
                "actors": all_actors,
                "hashtags": all_hashtags,
                "errors": errors
            })
        if path == "/api/conversations":
            if not CLIENTS:
                return self.send(200, {"conversations": [], "total_unread": 0, "errors": {}, "networks": []})
            qs = urllib.parse.parse_qs(parsed.query)
            target_net = qs.get("network", [None])[0]
            active_clients = [c for c in CLIENTS.values() if not target_net or c.name == target_net]
            all_convos = []
            errors = {}

            def fetch_convos(c):
                try:
                    return c.name, c.list_conversations(), None
                except Exception as e:
                    return c.name, None, str(e)

            for name, res, err in _API_EXECUTOR.map(fetch_convos, active_clients):
                if err:
                    errors[name] = err
                elif res:
                    all_convos.extend(res.get("convos", []))

            all_convos.sort(key=lambda c: parse_time(c.get("last_time")), reverse=True)
            total_unread = sum(1 for c in all_convos if c.get("unread"))
            return self.send(200, {
                "conversations": all_convos,
                "total_unread": total_unread,
                "errors": errors,
                "networks": list(CLIENTS)
            })
        if path == "/api/conversation":
            if not CLIENTS:
                return self.send(400, {"error": "Nenhuma rede configurada."})
            qs = urllib.parse.parse_qs(parsed.query)
            net = qs.get("network", [None])[0]
            cid = qs.get("id", [None])[0]
            if not net or net not in CLIENTS:
                return self.send(400, {"error": "Rede inválida ou não configurada."})
            if not cid:
                return self.send(400, {"error": "Parâmetro id em falta."})
            try:
                res = CLIENTS[net].get_conversation_messages(cid)
                return self.send(200, res)
            except Exception as e:
                return self.send(500, {"error": str(e)})
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
        global CFG, CLIENTS, SESSION_TOKEN
        if not self.allowed():
            return self.send(403, {"error": "forbidden"})
        token = self.headers.get("X-CSRF-Token")
        if not token or not hmac.compare_digest(token, SESSION_TOKEN):
            return self.send(403, {"error": "Token de sessão inválido ou ausente."})
        d, err = self._read_json()
        if err:
            return self.send(err[0], {"error": err[1]})
        results = {}
        if self.path == "/api/post":
            code, res = execute_post_payload(d)
            return self.send(code, res)
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
        if self.path == "/api/edit":
            net = (d.get("network") or "").strip().lower()
            ref = d.get("ref") or {}
            sid = ref.get("id") if isinstance(ref, dict) else d.get("id")
            if net != "mastodon" or net not in CLIENTS:
                return self.send(400, {"ok": False, "error": "Edição nativa apenas disponível para Mastodon configurado."})
            try:
                updated_item = CLIENTS[net].edit_status(
                    sid,
                    d.get("text") or "",
                    cw=d.get("cw") or "",
                    media_ids=d.get("media_ids") or None,
                )
                return self.send(200, {"ok": True, "item": updated_item})
            except Exception as e:
                return self.send(200, {"ok": False, "error": str(e)})
        if self.path == "/api/poll/vote":
            net = (d.get("network") or "mastodon").strip().lower()
            poll_id = d.get("poll_id")
            choices = d.get("choices")
            if net != "mastodon" or net not in CLIENTS:
                return self.send(400, {"ok": False, "error": "Sondagens apenas disponíveis no Mastodon configurado."})
            try:
                updated = CLIENTS[net].vote_poll(poll_id, choices)
                return self.send(200, {"ok": True, "poll": updated})
            except ValueError as ve:
                return self.send(400, {"ok": False, "error": str(ve)})
            except Exception as e:
                return self.send(200, {"ok": False, "error": str(e)})
        if self.path == "/api/follow":
            net = d.get("network")
            action = d.get("action")
            actor = d.get("actor")
            follow_uri = d.get("follow_uri")
            if not net or net not in CLIENTS:
                return self.send(400, {"error": "Rede inválida ou não configurada."})
            if action not in ("follow", "unfollow"):
                return self.send(400, {"error": "Ação inválida (deve ser 'follow' ou 'unfollow')."})
            if not actor:
                return self.send(400, {"error": "Identificador do utilizador em falta."})
            try:
                client = CLIENTS[net]
                if action == "follow":
                    res = client.follow(actor)
                    out = {"ok": True, "following": True}
                    if isinstance(res, dict) and "uri" in res:
                        out["follow_uri"] = res["uri"]
                    return self.send(200, out)
                else:
                    client.unfollow(actor, follow_uri=follow_uri)
                    return self.send(200, {"ok": True, "following": False})
            except Exception as e:
                return self.send(200, {"ok": False, "error": str(e)})
        if self.path == "/api/generate_alt":
            img_data = d.get("image")
            if not img_data or not isinstance(img_data, str):
                return self.send(400, {"ok": False, "error": "Imagem em falta ou inválida."})
            lang = d.get("lang")
            if lang is not None and not isinstance(lang, str):
                return self.send(400, {"ok": False, "error": "Idioma inválido."})
            try:
                alt_text = generate_alt_text(img_data, lang=lang)
                return self.send(200, {"ok": True, "alt": alt_text})
            except Exception as e:
                return self.send(200, {"ok": False, "error": str(e)})
        if self.path == "/api/translate":
            text_to_translate = d.get("text")
            if not text_to_translate or not isinstance(text_to_translate, str):
                return self.send(400, {"ok": False, "error": "Texto em falta ou inválido."})
            target_lang = d.get("target_lang")
            if target_lang is not None and not isinstance(target_lang, str):
                return self.send(400, {"ok": False, "error": "Idioma de destino inválido."})
            try:
                translated = translate_text(text_to_translate, target_lang=target_lang)
                return self.send(200, {"ok": True, "translated": translated, "target_lang": target_lang})
            except Exception as e:
                return self.send(200, {"ok": False, "error": str(e)})
        if self.path == "/api/catchup_summary":
            posts = d.get("posts")
            hours = d.get("hours", 12)
            lang = d.get("lang")
            try:
                summary = summarize_catchup_posts(posts, hours=hours, target_lang=lang)
                return self.send(200, {"ok": True, "summary": summary})
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
                inst = sanitize_masto_instance(m.get("instance"))
                tok = (m.get("token") or "").strip()
                if inst and tok:
                    new_cfg["mastodon"] = {"instance": inst, "token": tok}
                elif not inst and not tok and "mastodon" in new_cfg:
                    new_cfg.pop("mastodon", None)

            if "ai" in d:
                ai = d.get("ai")
                if isinstance(ai, dict):
                    prev_ai = new_cfg.get("ai", {}) if isinstance(new_cfg.get("ai"), dict) else {}
                    g_key = str(ai.get("gemini_key") or "").strip() or str(prev_ai.get("gemini_key") or "").strip()
                    o_key = str(ai.get("openai_key") or "").strip() or str(prev_ai.get("openai_key") or "").strip()
                    new_cfg["ai"] = {
                        "provider": str(ai.get("provider") or "none").strip(),
                        "lang": str(ai.get("lang") or "pt-pt").strip(),
                        "auto": bool(ai.get("auto", False)),
                        "gemini_key": g_key,
                        "gemini_model": str(ai.get("gemini_model") or "gemini-3.5-flash-lite").strip(),
                        "ollama_url": str(ai.get("ollama_url") or "http://localhost:11434").strip(),
                        "ollama_model": str(ai.get("ollama_model") or "llama3.2-vision").strip(),
                        "openai_url": str(ai.get("openai_url") or "https://api.openai.com/v1").strip(),
                        "openai_key": o_key,
                        "openai_model": str(ai.get("openai_model") or "gpt-4o-mini").strip(),
                    }
                elif ai is None and "ai" in new_cfg:
                    new_cfg.pop("ai", None)

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
        if self.path == "/api/self_update":
            try:
                msg = run_self_update()
                UPDATE_CACHE["data"] = None
                schedule_process_restart()
                return self.send(200, {"ok": True, "message": msg, "restarting": True})
            except Exception as e:
                return self.send(500, {"ok": False, "error": str(e)})
        if self.path == "/api/conversation/send":
            net = d.get("network")
            cid = d.get("convo_id")
            text = (d.get("text") or "").strip()
            recipient = d.get("recipient")
            last_msg_id = d.get("last_msg_id")
            if not net or net not in CLIENTS:
                return self.send(400, {"ok": False, "error": "Rede inválida ou não configurada."})
            if not text:
                return self.send(400, {"ok": False, "error": "Texto da mensagem não pode estar vazio."})
            try:
                if net == "bluesky":
                    msg = CLIENTS[net].send_message(cid, text)
                else:
                    msg = CLIENTS[net].send_message(cid, text, recipient=recipient, last_msg_id=last_msg_id)
                return self.send(200, {"ok": True, "message": msg})
            except Exception as e:
                return self.send(500, {"ok": False, "error": str(e)})

        if self.path == "/api/conversation/read":
            net = d.get("network")
            cid = d.get("convo_id")
            if not net or net not in CLIENTS:
                return self.send(400, {"ok": False, "error": "Rede inválida ou não configurada."})
            if not cid:
                return self.send(400, {"ok": False, "error": "Parâmetro convo_id em falta."})
            try:
                CLIENTS[net].mark_as_read(cid)
                return self.send(200, {"ok": True})
            except Exception as e:
                return self.send(500, {"ok": False, "error": str(e)})

        if self.path == "/api/conversation/start":
            net = d.get("network")
            recipient = (d.get("recipient") or "").strip()
            text = (d.get("text") or "").strip()
            if not net or net not in CLIENTS:
                return self.send(400, {"ok": False, "error": "Rede inválida ou não configurada."})
            if not recipient:
                return self.send(400, {"ok": False, "error": "Destinatário em falta."})
            try:
                res = CLIENTS[net].start_conversation(recipient, text=text)
                return self.send(200, {"ok": True, **res})
            except Exception as e:
                return self.send(500, {"ok": False, "error": str(e)})
        if self.path.split("?", 1)[0] == "/api/user_data":
            try:
                saved = save_user_data(d)
                return self.send(200, {"ok": True, "data": saved})
            except ValueError as e:
                return self.send(400, {"ok": False, "error": str(e)})
        if self.path == "/api/scheduled":
            raw_ts = d.get("scheduled_at")
            payload = d.get("payload")
            if not isinstance(raw_ts, (int, float)):
                return self.send(400, {"ok": False, "error": "Data/hora de agendamento inválida."})
            sched_ts = int(raw_ts)
            now_ts = int(time.time())
            if sched_ts <= now_ts - 30:
                return self.send(400, {"ok": False, "error": "A data de agendamento tem de ser no futuro."})
            vcode, vres = execute_post_payload(payload, validate_only=True)
            if vcode != 200:
                return self.send(vcode, {"ok": False, "error": vres.get("error", "Publicação inválida.")})
            new_item = {
                "id": uuid.uuid4().hex[:16],
                "scheduled_at": sched_ts,
                "created_at": now_ts,
                "updated_at": now_ts,
                "status": "pending",
                "payload": payload,
                "results": {},
                "error": ""
            }
            items = load_scheduled_posts()
            items.append(new_item)
            save_scheduled_posts(items)
            return self.send(200, {"ok": True, "item": new_item})
        if self.path == "/api/scheduled/update":
            item_id = d.get("id")
            raw_ts = d.get("scheduled_at")
            if not item_id or not isinstance(raw_ts, (int, float)):
                return self.send(400, {"ok": False, "error": "Parâmetros inválidos."})
            sched_ts = int(raw_ts)
            now_ts = int(time.time())
            if sched_ts <= now_ts - 30:
                return self.send(400, {"ok": False, "error": "A data de agendamento tem de ser no futuro."})
            items = load_scheduled_posts()
            updated = None
            for it in items:
                if it.get("id") == item_id:
                    it["scheduled_at"] = sched_ts
                    it["status"] = "pending"
                    it["error"] = ""
                    it["updated_at"] = now_ts
                    updated = it
                    break
            if not updated:
                return self.send(404, {"ok": False, "error": "Agendamento não encontrado."})
            save_scheduled_posts(items)
            return self.send(200, {"ok": True, "item": updated})
        if self.path == "/api/scheduled/delete":
            action = d.get("action")
            item_id = d.get("id")
            items = load_scheduled_posts()
            if action == "clear_published":
                items = [it for it in items if it.get("status") != "published"]
            elif item_id:
                before = len(items)
                items = [it for it in items if it.get("id") != item_id]
                if len(items) == before:
                    return self.send(404, {"ok": False, "error": "Agendamento não encontrado."})
            else:
                return self.send(400, {"ok": False, "error": "ID em falta."})
            save_scheduled_posts(items)
            return self.send(200, {"ok": True, "items": items})
        if self.path == "/api/scheduled/run_now":
            item_id = d.get("id")
            if not item_id:
                return self.send(400, {"ok": False, "error": "ID em falta."})
            updated = run_scheduled_item(item_id)
            if not updated:
                return self.send(404, {"ok": False, "error": "Agendamento não encontrado."})
            return self.send(200, {"ok": True, "item": updated})
        self.send(404, {"error": "not found"})


def main():
    global PORT, LAN_MODE, LISTEN_HOST
    parser = argparse.ArgumentParser(description="MastoSky: cliente local-first Bluesky + Mastodon.")
    parser.add_argument("--port", type=int, default=None, help="Porto HTTP local (por omissão: config.json ou 8000)")
    parser.add_argument("--lan", action="store_true", help="Permitir acesso de outros dispositivos na mesma rede local (Wi-Fi / LAN)")
    parser.add_argument("--host", type=str, default=None, help="Endereço de rede onde o servidor escuta (ex: 127.0.0.1 ou 0.0.0.0)")
    parser.add_argument("--open", action="store_true", help="Abrir automaticamente o navegador predefinido")
    parser.add_argument("--verbose", action="store_true", help="Ativar registo de pedidos HTTP em stderr")
    args = parser.parse_args()

    if args.port:
        PORT = args.port
    if args.verbose:
        H.verbose = True

    if args.lan:
        LAN_MODE = True
        LISTEN_HOST = args.host or "0.0.0.0"
    elif args.host:
        LISTEN_HOST = args.host
        if LISTEN_HOST in ("0.0.0.0", "::"):
            LAN_MODE = True

    server = ThreadingHTTPServer((LISTEN_HOST, PORT), H)
    local_url = f"http://127.0.0.1:{PORT}"

    if LAN_MODE:
        local_ip = get_local_ip()
        lan_url = f"http://{local_ip}:{PORT}"
        hname = socket.gethostname()
        mdns_url = f"http://{hname}.local:{PORT}" if hname and not hname.endswith(".local") else f"http://{hname}:{PORT}"

        print("\n" + "═" * 70)
        print("🚀 MastoSky a correr na Rede Local (Wi-Fi / LAN)")
        print(f"   • No teu computador:   {local_url}")
        print(f"   • No telemóvel / iPad: {lan_url}")
        if hname and hname != "127.0.0.1":
            print(f"                          (ou {mdns_url})")
        print("═" * 70)

        try:
            mat = generate_qr_matrix(lan_url, level='M')
            print("\n📱 Lê com a câmara do telemóvel / iPad:")
            print(qr_to_ascii(mat, margin=1))
        except Exception:
            pass

        print("💡 No navegador, podes também clicar no ícone 📱 no topo para ver o")
        print("   QR Code em alta definição e as instruções de instalação (PWA).")
        print("═" * 70 + "\n")
    else:
        print(f"MastoSky a correr em {local_url}  (Ctrl+C para parar)")
        print("💡 Dica: Para acederes no telemóvel / iPad via Wi-Fi, usa: python3 app.py --lan\n")

    if args.open:
        webbrowser.open(local_url)

    start_scheduler_thread()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nA encerrar MastoSky...")
        server.server_close()


if __name__ == "__main__":
    main()
