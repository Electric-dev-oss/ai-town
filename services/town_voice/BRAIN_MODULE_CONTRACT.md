# External dependency: `brain` module (not included)

`town_voice.py` loads `brain.py` from `$BOX_BRAINS_ROOT/<char>/`. That per-character runtime
(persona files, rails, and its memory store) stays outside this repository. There is no checked-in
brain for Lyra, Jolt, or any of the other Stormvale characters, and this package does not invent
one. A missing `brain.py` is a startup error. Convex then keeps the ordinary town model whenever
`BRAIN_TOWN` is unset, or falls back to it when a listed character's voice service fails.

The default proxy routes only name `lyra` and `jolt`. Enrique, Mira, Elian Marlowe, Demon Outlaw,
and Erebus Stormvale have character descriptions in `data/characters.ts` and no town-voice route
unless an operator adds one.

## API surface town_voice calls

- `B.CFG` dict with at least `model` (str) and `ollama_url` (str, Ollama `/api/generate`)
- `B.persona()` → object with `.prompt()` and `.temperature()`
- `B.rd(filename)` → read markdown/text helper (for example `identity.md`, `voice_guide.md`)
- `B.mem_all()` → iterable of memory dicts with optional `kind` and `text`
- `B.parse_json(raw)` → dict or None
- `B.clean(text)`, `B.tidy_line(text)` → str
- `B.too_similar(text)` → bool
- `B.sound_corporate(text)` → bool
- `B.PROMISE_MEMORY`, `B.RULE_SPEND`, `B.RULE_CONTACT` → compiled regexes with `.search`
- `B.remember(text, kind, n, src=...)` → persist a short action memory in that external store

`ollama_url` must be `http` or `https` and must not include userinfo. Redirects are not followed.

## Env

- `BOX_BRAINS_ROOT` — directory of per-character folders (`lyra`, `jolt`, …)
- `BRAIN_CTX` — optional Ollama `num_ctx` (default 1024)
- `BRAIN_CHARACTER` — set by town_voice to the `--char` value
- `TOWN_VOICE_LOG` — optional extra log file. Unset logs to stderr only

Tests should pass an in-memory fake with this surface. Do not publish private memory JSON or
identity files.
