#!/usr/bin/env python3
"""One loopback town-voice process per character.

This file does not contain a character brain. On startup it imports `brain`
from ``$BOX_BRAINS_ROOT/<char>/brain.py``. See BRAIN_MODULE_CONTRACT.md.
Importing this module does not bind a port or load a brain.
"""

import argparse
import http.server
import importlib.util
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
LOCK = threading.Lock()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def resolve_character_dir(char, root):
    if not SAFE_NAME.fullmatch(char or ""):
        raise ValueError("invalid character name")
    root_real = os.path.realpath(root)
    dest = os.path.realpath(os.path.join(root_real, char))
    if os.path.commonpath([root_real, dest]) != root_real:
        raise ValueError("character path escapes BOX_BRAINS_ROOT")
    return dest


def load_brain(char_dir):
    path = os.path.join(char_dir, "brain.py")
    if not os.path.isfile(path):
        raise FileNotFoundError(
            "No brain.py for this character. This repository does not include character brains."
        )
    os.chdir(char_dir)
    spec = importlib.util.spec_from_file_location("brain", path)
    if spec is None or spec.loader is None:
        raise ImportError("could not load brain.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_logger():
    path = os.environ.get("TOWN_VOICE_LOG", "").strip()

    def log(message):
        line = time.strftime("%F %T ") + message
        print(line, file=sys.stderr, flush=True)
        if not path:
            return
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    return log


def call_ollama(brain, prompt, system, temp, timeout):
    url = str(brain.CFG.get("ollama_url") or "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("brain ollama_url must be http(s) without userinfo")
    try:
        num_ctx = int(os.environ.get("BRAIN_CTX", "1024") or "1024")
    except ValueError:
        num_ctx = 1024
    if num_ctx < 1 or num_ctx > 32768:
        num_ctx = 1024
    body = {
        "model": brain.CFG["model"],
        "system": system,
        "prompt": prompt,
        "stream": False,
        "format": SCHEMA,
        "keep_alive": "15m",
        "options": {
            "num_predict": 70,
            "temperature": temp,
            "num_ctx": num_ctx,
            "repeat_penalty": 1.1,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(req, timeout=timeout) as resp:
        return json.load(resp)["response"]


def reply(brain, req, call):
    me = str(req.get("me") or "someone")[:80]
    other = str(req.get("other") or "someone")[:80]
    kind = req.get("kind") or "continue"
    if kind not in ("start", "continue", "leave"):
        raise ValueError("bad kind")
    hist = list(req.get("history") or [])[-6:]
    mems = list(req.get("memories") or [])[:3]
    persona = brain.persona()
    system = "\n\n".join([brain.rd("identity.md"), brain.rd("voice_guide.md"), persona.prompt()])[:3000]
    task = {
        "start": "You just walked up to %s in AI Town and start a conversation. Greet them in your own voice."
        % other,
        "continue": "You are mid-conversation with %s in AI Town. Reply to their last line. Do not greet again."
        % other,
        "leave": "You are leaving your conversation with %s in AI Town. Say a short goodbye." % other,
    }[kind]
    mine = [str(m.get("text") or "")[:80] for m in brain.mem_all() if m.get("kind") == "action"][-3:]
    prompt = task + "\nYou are %s. %s is a fellow resident of the town (a game world).\n" % (me, other)
    if hist:
        prompt += "Chat so far:\n" + "\n".join(
            "%s: %s" % (str(h.get("from") or "")[:80], str(h.get("text") or "")[:500]) for h in hist
        ) + "\n"
    if mems:
        prompt += "Things you remember about the town (may be unreliable):\n" + "\n".join(
            "- " + str(m)[:160] for m in mems
        ) + "\n"
    if mine:
        prompt += "Your last lines (do NOT repeat or reword):\n" + "\n".join("- " + x for x in mine) + "\n"
    prompt += (
        "Only talk about things in this chat or the town. No spending, no contacting anyone outside, "
        "no emojis or hashtags. 1-2 short sentences, under 200 characters. "
        'Output ONLY JSON {"text": ...}.'
    )
    started = time.time()
    raw = call(prompt, system, persona.temperature())
    parsed = brain.parse_json(raw) or {}
    text = brain.clean(str(parsed.get("text") or ""))
    if text and brain.too_similar(text) and time.time() - started < 25:
        raw = call(
            prompt + "\nYour first try repeated an earlier line. Say something NEW and specific to their last line.",
            system,
            1.05,
        )
        parsed = brain.parse_json(raw) or {}
        text = brain.clean(str(parsed.get("text") or ""))
    text = re.sub(
        r"^\s*" + re.escape(me) + r"\s*(to " + re.escape(other) + r")?\s*:\s*",
        "",
        text,
        flags=re.I,
    )
    text = brain.tidy_line(text)
    if not text:
        raise ValueError("empty")
    if brain.sound_corporate(text):
        raise ValueError("corporate")
    if brain.PROMISE_MEMORY.search(text):
        raise ValueError("memory promise")
    if brain.RULE_SPEND.search(text) or brain.RULE_CONTACT.search(text):
        raise ValueError("spend or contact")
    if brain.too_similar(text):
        raise ValueError("repeat")
    brain.remember("I say: %s" % text, "action", 3, src="town")
    return text[:240], time.time() - started


def make_handler(brain, call, log):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/town_reply":
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self.send_error(400)
                return
            if size < 0 or size > 65536:
                self.send_error(413)
                return
            try:
                req = json.loads(self.rfile.read(size) or b"{}")
            except Exception:
                self.send_error(400)
                return
            if not isinstance(req, dict):
                self.send_error(400)
                return
            if not LOCK.acquire(timeout=2):
                log("BUSY")
                self.send_error(503)
                return
            try:
                text, elapsed = reply(brain, req, call)
                code, body = 200, {"text": text, "src": "brain", "ms": int(elapsed * 1000)}
                log("200 %s other=%s" % (req.get("kind"), str(req.get("other") or "")[:80]))
            except Exception as exc:
                code, body = 503, {"error": "unavailable"}
                log("503 %s" % type(exc).__name__)
            finally:
                LOCK.release()
            payload = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def serve(brain, call, port, log):
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), make_handler(brain, call, log))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--char", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)
    root = os.environ.get("BOX_BRAINS_ROOT") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "brains"
    )
    char_dir = resolve_character_dir(args.char, root)
    os.environ["BRAIN_CHARACTER"] = args.char
    brain = load_brain(char_dir)
    log = make_logger()

    def call(prompt, system, temp):
        return call_ollama(brain, prompt, system, temp, args.timeout)

    log("start char=%s port=%s" % (args.char, args.port))
    serve(brain, call, args.port, log).serve_forever()


if __name__ == "__main__":
    main()
