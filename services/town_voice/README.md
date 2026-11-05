# town_voice

Optional loopback adapter. One process per character, bound to `127.0.0.1` only:

`python3 town_voice.py --char lyra --port 11501 --timeout 55`

`POST /town_reply` accepts JSON
`{me, other, kind: start|continue|leave, history:[{from,text}], memories?:[]}`. Success is
`{"text":"...","src":"brain","ms":N}`. Failure is HTTP 503 with `{"error":"unavailable"}` and no
generated line, so Convex can fall back to the town LLM.

This directory does not contain a character brain, persona, or memory store. At startup the process
imports `brain.py` from `$BOX_BRAINS_ROOT/<char>/` (default `services/brains/<char>/`, which is
gitignored). The required module surface is [BRAIN_MODULE_CONTRACT.md](./BRAIN_MODULE_CONTRACT.md).
Tests use an in-memory fake. Do not copy private brain data into this repository.

Logs go to stderr. Set `TOWN_VOICE_LOG` to also append them to a file. The log records status and
character metadata, not the reply text. `BRAIN_CTX` optionally sets Ollama `num_ctx` (default 1024).

Convex uses this service only when `BRAIN_TOWN` lists that character and `OLLAMA_HOST` is set. With
`BRAIN_TOWN` unset, AI Town never calls here.
