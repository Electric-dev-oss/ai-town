import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import proxy


class ClassifyTests(unittest.TestCase):
    def setUp(self):
        self.brains = dict(proxy.DEFAULT_BRAINS)
        self.secret = "example-path-prefix"

    def test_default_routes_are_only_lyra_and_jolt_on_loopback(self):
        self.assertEqual(
            self.brains,
            {
                "/lyra/town_reply": "http://127.0.0.1:11501",
                "/jolt/town_reply": "http://127.0.0.1:11502",
            },
        )

    def test_missing_secret_does_not_classify_the_path(self):
        self.assertEqual(proxy.classify("POST", "/v1/chat/completions", self.secret, self.brains)[0], "missing_secret")

    def test_allowlist_and_brain_routes(self):
        base = "/" + self.secret
        self.assertEqual(
            proxy.classify("POST", base + "/lyra/town_reply", self.secret, self.brains),
            ("brain", "http://127.0.0.1:11501", "/lyra/town_reply"),
        )
        self.assertEqual(proxy.classify("POST", base + "/v1/chat/completions", self.secret, self.brains)[0], "ollama")
        self.assertEqual(proxy.classify("GET", base + "/api/tags", self.secret, self.brains)[0], "ollama")
        self.assertEqual(proxy.classify("POST", base + "/api/pull", self.secret, self.brains)[0], "forbidden")
        self.assertEqual(proxy.classify("POST", base + "/enrique/town_reply", self.secret, self.brains)[0], "forbidden")
        self.assertEqual(proxy.classify("DELETE", base + "/v1/chat/completions", self.secret, self.brains)[0], "method")

    def test_query_string_is_stripped_before_matching(self):
        decision = proxy.classify(
            "POST", "/" + self.secret + "/lyra/town_reply?x=1", self.secret, self.brains
        )
        self.assertEqual(decision[0], "brain")

    def test_rejects_userinfo_and_nonlocal_upstreams(self):
        with self.assertRaises(SystemExit):
            proxy.check_upstream("http://user:pass@127.0.0.1:11434")
        with self.assertRaises(SystemExit):
            proxy.check_upstream("http://example.invalid:11434")
        with self.assertRaises(SystemExit):
            proxy.check_upstream("file:///etc/passwd")
        self.assertTrue(proxy.check_upstream("http://127.0.0.1:11434").startswith("http://127.0.0.1:11434"))


class SecretTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("OLLAMA_PROXY_SECRET", None)
        os.environ.pop("OLLAMA_PROXY_SECRET_FILE", None)

    def test_missing_secret_fails_without_a_default(self):
        os.environ.pop("OLLAMA_PROXY_SECRET", None)
        os.environ.pop("OLLAMA_PROXY_SECRET_FILE", None)
        with self.assertRaises(SystemExit):
            proxy.load_secret()

    def test_short_secret_is_rejected(self):
        os.environ["OLLAMA_PROXY_SECRET"] = "short"
        with self.assertRaises(SystemExit):
            proxy.load_secret()


class _Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(size)
        self.server.seen = (self.path, body)
        data = b'{"text":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        return


class ForwardTests(unittest.TestCase):
    def test_forwards_only_to_the_configured_loopback_brain(self):
        stub = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
        stub.seen = None
        thread = threading.Thread(target=stub.serve_forever, daemon=True)
        thread.start()
        port = stub.server_address[1]
        secret = "example-path-prefix"
        brains = {"/lyra/town_reply": "http://127.0.0.1:%d" % port}
        server = proxy.serve(secret, "http://127.0.0.1:%d" % port, brains, 0)
        proxy_thread = threading.Thread(target=server.serve_forever, daemon=True)
        proxy_thread.start()
        time.sleep(0.05)
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            payload = b'{"me":"Lyra"}'
            req = urllib.request.Request(
                "http://127.0.0.1:%d/%s/lyra/town_reply" % (server.server_address[1], secret),
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(json.load(resp)["text"], "ok")
            self.assertEqual(stub.seen[0], "/town_reply")
            self.assertEqual(stub.seen[1], payload)
            stub.seen = None
            bad = urllib.request.Request(
                "http://127.0.0.1:%d/wrong-path-prefix/lyra/town_reply" % server.server_address[1],
                data=payload,
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(bad, timeout=5)
            self.assertEqual(caught.exception.code, 404)
            self.assertIsNone(stub.seen)
        finally:
            server.shutdown()
            server.server_close()
            stub.shutdown()
            stub.server_close()


if __name__ == "__main__":
    unittest.main()
