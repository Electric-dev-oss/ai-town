import json
import os
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import town_voice


class FakePersona:
    def prompt(self):
        return "plain voice"

    def temperature(self):
        return 0.4


class FakeBrain:
    def __init__(self):
        self.CFG = {"model": "local-model", "ollama_url": "http://127.0.0.1:9/api/generate"}
        self.PROMISE_MEMORY = re.compile(r"I will remember")
        self.RULE_SPEND = re.compile(r"\bspend\b", re.I)
        self.RULE_CONTACT = re.compile(r"\bemail\b", re.I)
        self.remembered = None

    def persona(self):
        return FakePersona()

    def rd(self, name):
        return name

    def mem_all(self):
        return []

    def parse_json(self, raw):
        return json.loads(raw)

    def clean(self, text):
        return text.strip()

    def tidy_line(self, text):
        return text.strip()

    def too_similar(self, text):
        return False

    def sound_corporate(self, text):
        return "synergy" in text

    def remember(self, text, kind, n, src=None):
        self.remembered = (text, kind, n, src)


def _call_returning(raw):
    def call(prompt, system, temp):
        return raw

    return call


class ReplyTests(unittest.TestCase):
    def test_success_remembers_only_the_spoken_line(self):
        brain = FakeBrain()
        text, _elapsed = town_voice.reply(
            brain,
            {"me": "Lyra", "other": "Jolt", "kind": "continue", "history": [{"from": "Jolt", "text": "Hi"}]},
            _call_returning('{"text":"Good to see you."}'),
        )
        self.assertEqual(text, "Good to see you.")
        self.assertEqual(brain.remembered[0], "I say: Good to see you.")
        self.assertEqual(brain.remembered[3], "town")

    def test_rails_reject_without_echoing_the_line(self):
        brain = FakeBrain()
        with self.assertRaises(ValueError):
            town_voice.reply(brain, {"kind": "continue"}, _call_returning('{"text":"I will remember your secret phrase"}'))
        self.assertIsNone(brain.remembered)
        with self.assertRaises(ValueError):
            town_voice.reply(brain, {"kind": "continue"}, _call_returning('{"text":"Let us spend the afternoon."}'))

    def test_handler_hides_rejected_text(self):
        brain = FakeBrain()
        log_lines = []
        server = town_voice.serve(
            brain,
            _call_returning('{"text":"I will remember hunter-phrase"}'),
            0,
            log_lines.append,
        )
        self.assertEqual(server.server_address[0], "127.0.0.1")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.05)
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:%d/town_reply" % server.server_address[1],
                data=b'{"kind":"continue","other":"Jolt"}',
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req, timeout=5)
            body = caught.exception.read()
            self.assertEqual(caught.exception.code, 503)
            self.assertIn(b'"error": "unavailable"', body)
            self.assertNotIn(b"hunter-phrase", body)
            self.assertTrue(all("hunter-phrase" not in line for line in log_lines))
        finally:
            server.shutdown()
            server.server_close()

    def test_character_dir_rejects_escape_and_missing_brain(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                town_voice.resolve_character_dir("../secrets", tmp)
            with self.assertRaises(ValueError):
                town_voice.resolve_character_dir("lyra/../../etc", tmp)
            dest = town_voice.resolve_character_dir("lyra", tmp)
            self.assertTrue(dest.startswith(os.path.realpath(tmp)))
            with self.assertRaises(FileNotFoundError) as caught:
                town_voice.load_brain(dest)
            self.assertNotIn(tmp, str(caught.exception))

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = tempfile.mkdtemp()
            try:
                link = Path(tmp) / "lyra"
                link.symlink_to(outside)
                with self.assertRaises(ValueError):
                    town_voice.resolve_character_dir("lyra", tmp)
            finally:
                os.rmdir(outside)


class SourceAuditTests(unittest.TestCase):
    def test_service_sources_have_no_private_paths_or_key_material(self):
        root = Path(__file__).resolve().parents[1]
        blobs = []
        for path in root.rglob("*"):
            if path.name.startswith("test_"):
                continue
            if path.suffix.lower() in {".py", ".md"} and path.is_file():
                blobs.append(path.read_text(encoding="utf-8"))
        text = "\n".join(blobs)
        self.assertNotRegex(text, r"AKIA[0-9A-Z]{16}")
        self.assertNotRegex(text, r"-----BEGIN [A-Z ]+PRIVATE KEY-----")
        self.assertNotRegex(text, r"sk-[A-Za-z0-9]{20,}")
        self.assertNotIn("/home/", text)
        self.assertNotIn("/Users/", text)
        for match in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
            self.assertEqual(match, "127.0.0.1", match)


if __name__ == "__main__":
    unittest.main()
