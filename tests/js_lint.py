"""Lightweight JavaScript tokenizer and scope-aware undeclared-identifier checker."""

import re

JS_KEYWORDS = {
    "break", "case", "catch", "class", "const", "continue", "debugger", "default",
    "delete", "do", "else", "export", "extends", "finally", "for", "function",
    "if", "import", "in", "instanceof", "let", "new", "return", "super",
    "switch", "this", "throw", "try", "typeof", "var", "void", "while", "with",
    "yield", "async", "await", "of", "as", "from", "get", "set", "static",
    "true", "false", "null", "undefined", "NaN", "Infinity", "arguments",
}

BROWSER_GLOBALS = {
    "window", "document", "self", "globalThis", "navigator", "location", "history",
    "localStorage", "sessionStorage", "console", "fetch", "URL", "URLSearchParams",
    "FormData", "Blob", "File", "FileReader", "Image", "Audio", "Video", "Option",
    "XMLHttpRequest", "AbortController", "AbortSignal", "Headers", "Request", "Response",
    "Event", "CustomEvent", "KeyboardEvent", "MouseEvent", "InputEvent", "ClipboardEvent",
    "IntersectionObserver", "MutationObserver", "ResizeObserver", "DOMParser",
    "Node", "Element", "HTMLElement", "HTMLCanvasElement", "CanvasRenderingContext2D",
    "Intl", "Math", "JSON", "Date", "RegExp", "Error", "TypeError", "RangeError",
    "SyntaxError", "ReferenceError", "Promise", "Set", "Map", "WeakSet", "WeakMap",
    "Array", "Object", "String", "Number", "Boolean", "Symbol", "BigInt", "Function",
    "Reflect", "Proxy", "Uint8Array", "Uint16Array", "Uint32Array", "Int32Array",
    "ArrayBuffer", "DataView", "TextEncoder", "TextDecoder",
    "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "requestAnimationFrame", "cancelAnimationFrame", "queueMicrotask",
    "alert", "confirm", "prompt", "open", "close", "print", "focus", "blur",
    "atob", "btoa", "encodeURIComponent", "decodeURIComponent", "encodeURI", "decodeURI",
    "isNaN", "isFinite", "parseInt", "parseFloat", "structuredClone",
    "crypto", "performance", "getComputedStyle", "matchMedia", "scrollTo", "scrollBy",
    "getSelection", "DataTransfer", "ClipboardItem", "Notification", "WebSocket",
    "EventSource", "Worker", "Hls", "CSS", "MASTOSKY_SESSION_TOKEN",
}

REGEX_PREV_TOKENS = {
    "(", "[", "{", ",", ";", ":", "?", "=", "+=", "-=", "*=", "/=", "%=",
    "&&", "||", "??", "!", "~", "+", "-", "*", "/", "%", "<", ">", "<=", ">=",
    "==", "!=", "===", "!==", "&", "|", "^", "<<", ">>", ">>>", "=>",
    "return", "throw", "case", "in", "instanceof", "typeof", "void", "delete",
    "new", "else", "do", "yield", "await",
}

MULTI_CHAR_OPS = (
    ">>>=", "===", "!==", ">>>", "<<=", ">>=", "**=", "&&=", "||=", "??=",
    "...", "=>", "?.", "??", "&&", "||", "==", "!=", "<=", ">=", "++", "--",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<", ">>", "**",
)


def tokenize_js(code):
    """Tokenize JS into (kind, value, line) tuples, handling strings, templates, comments, and regexes."""
    tokens = []
    n = len(code)
    i = 0
    line = 1
    template_stack = []

    def prev_significant():
        return tokens[-1][1] if tokens else None

    while i < n:
        ch = code[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch in " \t\r":
            i += 1
            continue

        if ch == "/" and i + 1 < n and code[i + 1] == "/":
            i += 2
            while i < n and code[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and code[i + 1] == "*":
            i += 2
            while i + 1 < n and not (code[i] == "*" and code[i + 1] == "/"):
                if code[i] == "\n":
                    line += 1
                i += 1
            i += 2
            continue

        if ch == "/" and (not tokens or prev_significant() in REGEX_PREV_TOKENS):
            j = i + 1
            in_class = False
            ok = False
            while j < n:
                c = code[j]
                if c == "\n":
                    break
                if c == "\\":
                    j += 2
                    continue
                if c == "[":
                    in_class = True
                elif c == "]" and in_class:
                    in_class = False
                elif c == "/" and not in_class:
                    j += 1
                    while j < n and code[j].isalpha():
                        j += 1
                    ok = True
                    break
                j += 1
            if ok:
                tokens.append(("REGEX", code[i:j], line))
                i = j
                continue

        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            while j < n:
                c = code[j]
                if c == "\\":
                    if j + 1 < n and code[j + 1] == "\n":
                        line += 1
                    j += 2
                    continue
                if c == "\n":
                    line += 1
                if c == quote:
                    j += 1
                    break
                j += 1
            tokens.append(("STR", code[i:j], line))
            i = j
            continue

        if ch == "`":
            i += 1
            tokens.append(("TPL_START", "`", line))
            while i < n:
                c = code[i]
                if c == "\\":
                    if i + 1 < n and code[i + 1] == "\n":
                        line += 1
                    i += 2
                    continue
                if c == "\n":
                    line += 1
                if c == "`":
                    i += 1
                    tokens.append(("TPL_END", "`", line))
                    break
                if c == "$" and i + 1 < n and code[i + 1] == "{":
                    i += 2
                    tokens.append(("TPL_EXPR_START", "${", line))
                    template_stack.append(0)
                    break
                i += 1
            continue

        if ch == "}" and template_stack and template_stack[-1] == 0:
            template_stack.pop()
            i += 1
            tokens.append(("TPL_EXPR_END", "}", line))
            while i < n:
                c = code[i]
                if c == "\\":
                    if i + 1 < n and code[i + 1] == "\n":
                        line += 1
                    i += 2
                    continue
                if c == "\n":
                    line += 1
                if c == "`":
                    i += 1
                    tokens.append(("TPL_END", "`", line))
                    break
                if c == "$" and i + 1 < n and code[i + 1] == "{":
                    i += 2
                    tokens.append(("TPL_EXPR_START", "${", line))
                    template_stack.append(0)
                    break
                i += 1
            continue

        if ch == "{" and template_stack:
            template_stack[-1] += 1
        elif ch == "}" and template_stack:
            template_stack[-1] -= 1

        if ch.isdigit() or (ch == "." and i + 1 < n and code[i + 1].isdigit()):
            j = i
            while j < n and (code[j].isalnum() or code[j] in "._"):
                j += 1
            tokens.append(("NUM", code[i:j], line))
            i = j
            continue

        if ch.isalpha() or ch in ("_", "$"):
            j = i + 1
            while j < n and (code[j].isalnum() or code[j] in ("_", "$")):
                j += 1
            val = code[i:j]
            kind = "KW" if val in JS_KEYWORDS else "ID"
            tokens.append((kind, val, line))
            i = j
            continue

        matched = None
        for op in MULTI_CHAR_OPS:
            if code.startswith(op, i):
                matched = op
                break
        if matched:
            tokens.append(("OP", matched, line))
            i += len(matched)
            continue

        tokens.append(("OP", ch, line))
        i += 1

    return tokens


def find_undeclared_identifiers(scripts):
    """Analyze JS script blocks and return list of (ident, line) for undeclared references."""
    tokens = []
    for s in scripts:
        tokens.extend(tokenize_js(s))
    ntok = len(tokens)

    match = {}
    stack = []
    for idx, (_, val, _) in enumerate(tokens):
        if val in ("(", "[", "{", "${"):
            stack.append(idx)
        elif val in (")", "]", "}") and stack:
            if val == "}" and tokens[stack[-1]][1] not in ("{", "${"):
                continue
            open_idx = stack.pop()
            match[open_idx] = idx
            match[idx] = open_idx

    def extract_pattern_names(start, end, target_set):
        i = start
        while i < end:
            k, v, _ = tokens[i]
            if v == "=":
                depth = 0
                i += 1
                while i < end:
                    tv = tokens[i][1]
                    if tv in ("(", "[", "{", "${"):
                        depth += 1
                    elif tv in (")", "]", "}"):
                        if depth == 0:
                            break
                        depth -= 1
                    elif tv == "," and depth == 0:
                        break
                    i += 1
                continue
            if k == "ID":
                if i + 1 < end and tokens[i + 1][1] == ":":
                    i += 2
                    continue
                target_set.add(v)
            i += 1

    scopes = [set(BROWSER_GLOBALS)]
    fn_scope_indices = [0]

    def declare_var(name, hoist=False):
        if hoist:
            scopes[fn_scope_indices[-1]].add(name)
        else:
            scopes[-1].add(name)

    def is_declared(name):
        for s in reversed(scopes):
            if name in s:
                return True
        return False

    def hoist_in_range(start, end, target_fn_scope, is_top_level=False):
        i = start
        while i < end:
            _, v, _ = tokens[i]
            if v in ("{", "("):
                if v == "{" and i in match:
                    prev_v = tokens[i - 1][1] if i > 0 else ""
                    if prev_v in (")", "=>"):
                        i = match[i] + 1
                        continue
                i += 1
                continue
            if v == "function":
                if i + 1 < end and tokens[i + 1][0] == "ID":
                    target_fn_scope.add(tokens[i + 1][1])
                elif i + 1 < end and tokens[i + 1][1] == "*" and i + 2 < end and tokens[i + 2][0] == "ID":
                    target_fn_scope.add(tokens[i + 2][1])
            elif v == "var" or (is_top_level and v in ("let", "const", "class")):
                j = i + 1
                depth = 0
                in_init = False
                while j < end:
                    tk, tv, _ = tokens[j]
                    if tv in ("(", "[", "{", "${"):
                        if not in_init and tv in ("[", "{") and j in match:
                            end_p = match[j]
                            extract_pattern_names(j + 1, end_p, target_fn_scope)
                            j = end_p + 1
                            continue
                        depth += 1
                    elif tv in (")", "]", "}"):
                        if depth == 0:
                            break
                        depth -= 1
                    elif tv == "=" and depth == 0:
                        in_init = True
                    elif tv == "," and depth == 0:
                        in_init = False
                    elif tv == ";" and depth == 0:
                        break
                    elif tk == "ID" and not in_init and depth == 0:
                        if tv in ("in", "of"):
                            break
                        target_fn_scope.add(tv)
                    j += 1
            i += 1

    hoist_in_range(0, ntok, scopes[0], is_top_level=True)
    undeclared = []

    def walk(start, end):
        i = start
        while i < end:
            k, v, line = tokens[i]

            if v == "function":
                fn_name = None
                j = i + 1
                if j < end and tokens[j][1] == "*":
                    j += 1
                if j < end and tokens[j][0] == "ID":
                    fn_name = tokens[j][1]
                    j += 1
                if j < end and tokens[j][1] == "(" and j in match:
                    param_end = match[j]
                    body_start = param_end + 1
                    if body_start < end and tokens[body_start][1] == "{" and body_start in match:
                        body_end = match[body_start]
                        fn_scope = set()
                        if fn_name:
                            fn_scope.add(fn_name)
                        extract_pattern_names(j + 1, param_end, fn_scope)
                        hoist_in_range(body_start + 1, body_end, fn_scope)
                        scopes.append(fn_scope)
                        fn_scope_indices.append(len(scopes) - 1)
                        walk(j + 1, param_end)
                        walk(body_start + 1, body_end)
                        fn_scope_indices.pop()
                        scopes.pop()
                        i = body_end + 1
                        continue

            if v == "(" and i in match:
                close_p = match[i]
                if close_p + 1 < end and tokens[close_p + 1][1] == "=>":
                    fn_scope = set()
                    extract_pattern_names(i + 1, close_p, fn_scope)
                    body_start = close_p + 2
                    scopes.append(fn_scope)
                    fn_scope_indices.append(len(scopes) - 1)
                    walk(i + 1, close_p)
                    if body_start < end and tokens[body_start][1] == "{" and body_start in match:
                        body_end = match[body_start]
                        hoist_in_range(body_start + 1, body_end, fn_scope)
                        walk(body_start + 1, body_end)
                        fn_scope_indices.pop()
                        scopes.pop()
                        i = body_end + 1
                        continue
                    depth = 0
                    b_end = body_start
                    while b_end < end:
                        tv = tokens[b_end][1]
                        if tv in ("(", "[", "{", "${"):
                            depth += 1
                        elif tv in (")", "]", "}"):
                            if depth == 0:
                                break
                            depth -= 1
                        elif tv in (",", ";") and depth == 0:
                            break
                        b_end += 1
                    walk(body_start, b_end)
                    fn_scope_indices.pop()
                    scopes.pop()
                    i = b_end
                    continue

            if k == "ID" and i + 1 < end and tokens[i + 1][1] == "=>":
                fn_scope = {v}
                body_start = i + 2
                scopes.append(fn_scope)
                fn_scope_indices.append(len(scopes) - 1)
                if body_start < end and tokens[body_start][1] == "{" and body_start in match:
                    body_end = match[body_start]
                    hoist_in_range(body_start + 1, body_end, fn_scope)
                    walk(body_start + 1, body_end)
                    fn_scope_indices.pop()
                    scopes.pop()
                    i = body_end + 1
                    continue
                depth = 0
                b_end = body_start
                while b_end < end:
                    tv = tokens[b_end][1]
                    if tv in ("(", "[", "{", "${"):
                        depth += 1
                    elif tv in (")", "]", "}"):
                        if depth == 0:
                            break
                        depth -= 1
                    elif tv in (",", ";") and depth == 0:
                        break
                    b_end += 1
                walk(body_start, b_end)
                fn_scope_indices.pop()
                scopes.pop()
                i = b_end
                continue

            if v == "catch":
                j = i + 1
                catch_vars = set()
                if j < end and tokens[j][1] == "(" and j in match:
                    extract_pattern_names(j + 1, match[j], catch_vars)
                    j = match[j] + 1
                if j < end and tokens[j][1] == "{" and j in match:
                    body_end = match[j]
                    scopes.append(catch_vars)
                    walk(j + 1, body_end)
                    scopes.pop()
                    i = body_end + 1
                    continue

            if v == "for" and i + 1 < end and tokens[i + 1][1] == "(" and (i + 1) in match:
                hdr_end = match[i + 1]
                scopes.append(set())
                walk(i + 2, hdr_end)
                if hdr_end + 1 < end and tokens[hdr_end + 1][1] == "{" and (hdr_end + 1) in match:
                    body_end = match[hdr_end + 1]
                    walk(hdr_end + 2, body_end)
                    scopes.pop()
                    i = body_end + 1
                    continue
                stmt_end = hdr_end + 1
                s_depth = 0
                while stmt_end < end:
                    tv = tokens[stmt_end][1]
                    if tv in ("(", "[", "{", "${"):
                        s_depth += 1
                    elif tv in (")", "]", "}"):
                        if s_depth == 0:
                            break
                        s_depth -= 1
                    elif tv == ";" and s_depth == 0:
                        stmt_end += 1
                        break
                    stmt_end += 1
                walk(hdr_end + 1, stmt_end)
                scopes.pop()
                i = stmt_end
                continue

            if v == "{" and i in match:
                prev_v = tokens[i - 1][1] if i > 0 else ";"
                if prev_v in (";", "{", "}", ")", "else", "try", "finally", "do"):
                    b_end = match[i]
                    scopes.append(set())
                    walk(i + 1, b_end)
                    scopes.pop()
                    i = b_end + 1
                    continue

            if v in ("let", "const", "var", "class"):
                hoist = v == "var"
                j = i + 1
                depth = 0
                in_init = False
                while j < end:
                    tk, tv, _ = tokens[j]
                    if tv in ("(", "[", "{", "${"):
                        if not in_init and tv in ("[", "{") and j in match:
                            target = scopes[fn_scope_indices[-1]] if hoist else scopes[-1]
                            extract_pattern_names(j + 1, match[j], target)
                            j = match[j] + 1
                            continue
                        depth += 1
                    elif tv in (")", "]", "}"):
                        if depth == 0:
                            break
                        depth -= 1
                    elif tv == "=" and depth == 0:
                        in_init = True
                        init_start = j + 1
                        init_depth = 0
                        k2 = init_start
                        while k2 < end:
                            t2 = tokens[k2][1]
                            if t2 in ("(", "[", "{", "${"):
                                init_depth += 1
                            elif t2 in (")", "]", "}"):
                                if init_depth == 0:
                                    break
                                init_depth -= 1
                            elif t2 in (",", ";") and init_depth == 0:
                                break
                            k2 += 1
                        walk(init_start, k2)
                        j = k2
                        continue
                    elif tv == "," and depth == 0:
                        in_init = False
                    elif tv == ";" and depth == 0:
                        break
                    elif tk == "ID" and not in_init and depth == 0:
                        if tv in ("in", "of"):
                            walk(j + 1, end)
                            j = end
                            break
                        declare_var(tv, hoist=hoist)
                    j += 1
                i = j + 1 if j < end and tokens[j][1] == ";" else j
                continue

            if k == "ID":
                prev_v = tokens[i - 1][1] if i > 0 else None
                next_v = tokens[i + 1][1] if i + 1 < ntok else None
                if prev_v in (".", "?.") or prev_v == "typeof":
                    i += 1
                    continue
                if next_v == ":" and prev_v in ("{", ","):
                    i += 1
                    continue
                if next_v == "(" and prev_v in ("{", ",") and (i + 1) in match:
                    after_p = match[i + 1] + 1
                    if after_p < ntok and tokens[after_p][1] == "{":
                        if not (i >= 2 and tokens[i - 2][1] in (")", "else")):
                            i += 1
                            continue
                if not is_declared(v):
                    undeclared.append((v, line))

            i += 1

    walk(0, ntok)
    return undeclared


def check_html_undeclared_js(html):
    """Extract inline <script> blocks from HTML and return undeclared JS identifiers."""
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    return find_undeclared_identifiers(scripts)
