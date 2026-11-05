# ollama_proxy

Optional loopback reverse proxy in front of Ollama and town-voice routes. It is not required for
ordinary AI Town play. The process binds `127.0.0.1` only and does not start when the module is
imported.

## Env

- `OLLAMA_PROXY_SECRET` — path-prefix secret (one segment, at least 8 characters), or
- `OLLAMA_PROXY_SECRET_FILE` — file containing that secret on a single line
- `OLLAMA_UPSTREAM` — Ollama base URL. Default `http://127.0.0.1:11434`
- `OLLAMA_PROXY_PORT` — default `11500`
- `BRAIN_UPSTREAMS` — optional comma-separated `name=url` list. Default routes are only
  `lyra=http://127.0.0.1:11501` and `jolt=http://127.0.0.1:11502`
- `ALLOW_NONLOCAL_UPSTREAM=1` — required before an upstream host other than loopback is accepted

Upstream URLs must be `http` or `https` and must not contain userinfo. Redirects are not followed.
There is no default secret and this repository does not contain one.

Convex `OLLAMA_HOST` should be the proxy base including the secret prefix, for example
`https://<your-host>/<OLLAMA_PROXY_SECRET>`. Chat requests then use
`OLLAMA_HOST + /v1/chat/completions`, and a brain request for Lyra uses
`OLLAMA_HOST + /lyra/town_reply`. Never commit the secret.

Allowed Ollama paths are `POST /api/chat`, `/api/generate`, `/api/embeddings`, `/api/embed`,
`/v1/chat/completions`, `/v1/embeddings`, and `GET /api/tags`. Other paths, including `/api/pull`,
are rejected.

The other five Stormvale characters have no default proxy route and no brain in this repository. Add
a route only when that character's external `brain.py` is actually running.
