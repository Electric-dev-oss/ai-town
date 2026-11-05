import { brainTownReply, redactSensitive } from './llm';

const originalHost = process.env.OLLAMA_HOST;
const originalFetch = global.fetch;

function installFetch(impl: (input: RequestInfo | URL, init?: RequestInit) => Promise<unknown>) {
  const calls: [RequestInfo | URL, RequestInit | undefined][] = [];
  global.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    calls.push([input, init]);
    return impl(input, init);
  }) as typeof fetch;
  return calls;
}

afterEach(() => {
  if (originalHost === undefined) {
    delete process.env.OLLAMA_HOST;
  } else {
    process.env.OLLAMA_HOST = originalHost;
  }
  global.fetch = originalFetch;
});

test('brainTownReply does not fetch when OLLAMA_HOST is unset', async () => {
  delete process.env.OLLAMA_HOST;
  const calls = installFetch(() => Promise.reject(new Error('fetch should not be called')));
  await expect(
    brainTownReply('lyra', { me: 'Lyra', other: 'Jolt', kind: 'start', history: [] }, 1000),
  ).resolves.toBeNull();
  expect(calls).toHaveLength(0);
});

test('brainTownReply refuses unsafe character names without fetching', async () => {
  process.env.OLLAMA_HOST = 'http://127.0.0.1:9/example-path-prefix';
  const calls = installFetch(() => Promise.reject(new Error('fetch should not be called')));
  await expect(
    brainTownReply('../lyra', { me: 'Lyra', other: 'Jolt', kind: 'start', history: [] }, 1000),
  ).resolves.toBeNull();
  await expect(
    brainTownReply(
      'elian marlowe',
      { me: 'Elian', other: 'Jolt', kind: 'start', history: [] },
      1000,
    ),
  ).resolves.toBeNull();
  expect(calls).toHaveLength(0);
});

test('brainTownReply returns trimmed text and ignores a non-ok response', async () => {
  process.env.OLLAMA_HOST = 'http://127.0.0.1:9/example-path-prefix';
  const responses = [
    { ok: true, json: () => Promise.resolve({ text: '  hello there  ' }) },
    { ok: false, json: () => Promise.resolve({ text: 'nope' }) },
  ];
  const calls = installFetch(() => Promise.resolve(responses.shift()));
  const payload = { me: 'Lyra', other: 'Jolt', kind: 'continue' as const, history: [] };
  await expect(brainTownReply('lyra', payload, 1000)).resolves.toBe('hello there');
  await expect(brainTownReply('lyra', payload, 1000)).resolves.toBeNull();
  const [url, init] = calls[0];
  expect(url).toBe('http://127.0.0.1:9/example-path-prefix/lyra/town_reply');
  expect(init?.redirect).toBe('error');
  expect(JSON.parse(String(init?.body))).toEqual(payload);
  expect(JSON.parse(String(init?.body))).not.toHaveProperty('memories');
});

test('fetch failures redact the proxy path prefix', async () => {
  const secret = 'pathprefix-do-not-log';
  process.env.OLLAMA_HOST = `http://127.0.0.1:9/${secret}`;
  installFetch((input) =>
    Promise.reject(new Error(`connect ECONNREFUSED ${String(input)} Bearer sk-test-token-value`)),
  );
  await expect(
    brainTownReply('jolt', { me: 'Jolt', other: 'Lyra', kind: 'leave', history: [] }, 1000),
  ).rejects.toThrow(/<redacted>/);
  try {
    await brainTownReply('jolt', { me: 'Jolt', other: 'Lyra', kind: 'leave', history: [] }, 1000);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    expect(message).not.toContain(secret);
    expect(message).not.toContain('sk-test-token-value');
    expect(message).toContain('<redacted>');
  }
});

test('redactSensitive strips userinfo and query strings', () => {
  delete process.env.OLLAMA_HOST;
  expect(redactSensitive('https://user:pass@127.0.0.1/secret-segment/v1?token=abc')).toBe(
    'https://127.0.0.1/<redacted>/v1',
  );
});
