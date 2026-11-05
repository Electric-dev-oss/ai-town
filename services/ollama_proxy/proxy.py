#!/usr/bin/env python3
"""Loopback reverse proxy in front of Ollama and optional town_voice routes.

The path-prefix secret comes only from the environment. This module does not
start a listener on import. Bind address is always 127.0.0.1.
"""

import http.server
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

POSTS = {
    "/api/chat",
    "/api/generate",
    "/api/embeddings",
    "/api/embed",
    "/v1/chat/completions",
    "/v1/embeddings",
}
GETS = {"/api/tags"}
DEFAULT_UPSTREAM = "http://127.0.0.1:11434"
DEFAULT_BRAINS = {
    "/lyra/town_reply": "http://127.0.0.1:11501",
    "/jolt/town_reply": "http://127.0.0.1:11502",
}
MAX_OLLAMA_BYTES = 2 * 1024 * 1024
MAX_BRAIN_BYTES = 65536
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def check_upstream(url):
    parsed = urllib.parse.urlparse(url.strip())
    host = parsed.hostname
    if parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password:
        raise SystemExit("upstream must be http(s) without userinfo")
    if host not in LOOPBACK_HOSTS and os.environ.get("ALLOW_NONLOCAL_UPSTREAM") != "1":
        raise SystemExit("upstream host must be loopback unless ALLOW_NONLOCAL_UPSTREAM=1")
    return url.strip().rstrip("/")


def load_secret():
    inline = os.environ.get("OLLAMA_PROXY_SECRET", "").strip()
    if inline:
        secret = inline
    else:
        path = os.environ.get("OLLAMA_PROXY_SECRET_FILE", "").strip()
        if not path:
            raise SystemExit("OLLAMA_PROXY_SECRET or OLLAMA_PROXY_SECRET_FILE is required")
        mode = os.stat(path).st_mode
        if mode & 0o077:
            print("warning: secret file is readable by group or others", file=sys.stderr)
        with open(path, "r", encoding="utf-8") as handle:
            secret = handle.read(512).strip()
    if len(secret) < 8 or any(ch in secret for ch in "/\\?#\r\n\t "):
        raise SystemExit("proxy secret must be one path segment of at least 8 characters")
    return secret


def load_brains():
    raw = os.environ.get("BRAIN_UPSTREAMS", "").strip()
    if not raw:
        return dict(DEFAULT_BRAINS)
    brains = {}
    for part in raw.split(","):
        if "=" not in part:
            raise SystemExit("BRAIN_UPSTREAMS entries must look like name=http://127.0.0.1:port")
        name, url = part.split("=", 1)
        name = name.strip().lower()
        if not _NAME.fullmatch(name):
            raise SystemExit("invalid brain route name")
        brains["/%s/town_reply" % name] = check_upstream(url)
    return brains


def classify(method, path, secret, brains):
    prefix = "/" + secret
    if not path.startswith(prefix + "/"):
        return ("missing_secret",)
    relay = path[len(prefix) :].split("?", 1)[0]
    if method == "POST" and relay in brains:
        return ("brain", brains[relay], relay)
    if (method == "POST" and relay in POSTS) or (method == "GET" and relay in GETS):
        return ("ollama", relay)
    if method not in ("GET", "POST"):
        return ("method",)
    return ("forbidden", relay)


def _opener():
    return urllib.request.build_opener(_NoRedirect)


def _log(method, label, code):
    print("%s %s %s %s" % (time.strftime("%F %T"), method, label, code), flush=True)


def build_handler(secret, upstream, brains):
    opener = _opener()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            _log("PUT", "-", 405)
            self.send_error(405)

        do_PATCH = do_HEAD = do_DELETE = do_PUT

        def _handle(self, method):
            decision = classify(method, self.path, secret, brains)
            kind = decision[0]
            if kind == "missing_secret":
                _log(method, "<nosecret>", 404)
                self.send_error(404)
                return
            if kind == "method":
                _log(method, "-", 405)
                self.send_error(405)
                return
            if kind == "forbidden":
                _log(method, decision[1], 403)
                self.send_error(403)
                return
            if kind == "brain":
                self._brain(decision[1], decision[2])
                return
            self._ollama(method, decision[1])

        def _read(self, limit):
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                size = limit + 1
            if size < 0 or size > limit:
                return None
            return self.rfile.read(size)

        def _ollama(self, method, relay):
            body = None
            if method == "POST":
                body = self._read(MAX_OLLAMA_BYTES)
                if body is None:
                    _log(method, relay, 413)
                    self.send_error(413)
                    return
            req = urllib.request.Request(
                upstream + relay,
                data=body,
                method=method,
                headers={"Content-Type": "application/json"},
            )
            try:
                upstream_resp = opener.open(req, timeout=600)
                code = upstream_resp.status
            except urllib.error.HTTPError as exc:
                upstream_resp = exc
                code = exc.code
            except Exception:
                _log(method, relay, 502)
                self.send_error(502)
                return
            self.send_response(code)
            self.send_header(
                "Content-Type", upstream_resp.headers.get("Content-Type", "application/json")
            )
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                chunk = upstream_resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n" % len(chunk) + chunk + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            _log(method, relay, code)

        def _brain(self, base, relay):
            body = self._read(MAX_BRAIN_BYTES)
            if body is None:
                _log("POST", relay, 413)
                self.send_error(413)
                return
            started = time.time()
            req = urllib.request.Request(
                base + "/town_reply",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                upstream_resp = opener.open(req, timeout=70)
                code = upstream_resp.status
                out = upstream_resp.read()
            except urllib.error.HTTPError as exc:
                code = exc.code
                out = exc.read()
            except Exception:
                _log("POST", relay, 502)
                self.send_error(502)
                return
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            _log("POST", relay, "%s brain %.1fs" % (code, time.time() - started))

    return Handler


def serve(secret, upstream, brains, port):
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", port), build_handler(secret, upstream, brains)
    )
    return server


def main():
    secret = load_secret()
    upstream = check_upstream(os.environ.get("OLLAMA_UPSTREAM", DEFAULT_UPSTREAM))
    brains = load_brains()
    port = int(os.environ.get("OLLAMA_PROXY_PORT", "11500"))
    serve(secret, upstream, brains, port).serve_forever()


if __name__ == "__main__":
    main()
