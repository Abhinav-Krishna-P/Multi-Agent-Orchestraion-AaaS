import test from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import { Agent, AgentError } from '../dist/index.js'

async function serve(status, body, headers = {}) {
  const seen = {}
  const server = http.createServer((req, res) => {
    let raw = ''
    req.on('data', (c) => (raw += c))
    req.on('end', () => {
      seen.method = req.method
      seen.path = req.url
      seen.auth = req.headers.authorization
      seen.body = JSON.parse(raw)
      res.writeHead(status, { 'Content-Type': 'application/json', ...headers })
      res.end(typeof body === 'string' ? body : JSON.stringify(body))
    })
  })
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  return { seen, url: `http://127.0.0.1:${server.address().port}`, close: () => server.close() }
}

test('run sends key and message', async () => {
  const reply = { id: '1', agent_id: 'a', reply: 'yo', sources: [], tools_used: [], duration_ms: 5 }
  const s = await serve(200, reply)
  try {
    const out = await new Agent({ apiKey: 'cap_test', baseUrl: s.url }).run('hi')
    assert.deepEqual(out, reply)
    assert.equal(s.seen.method, 'POST')
    assert.equal(s.seen.path, '/v1/run')
    assert.equal(s.seen.auth, 'Bearer cap_test')
    assert.deepEqual(s.seen.body, { message: 'hi' })
  } finally {
    s.close()
  }
})

test('errors throw AgentError', async () => {
  const s = await serve(429, { detail: { code: 'rate_limited', message: 'Slow down' } }, { 'Retry-After': '7' })
  try {
    await assert.rejects(new Agent({ apiKey: 'k', baseUrl: s.url }).run('hi'), (e) => {
      assert.ok(e instanceof AgentError)
      assert.equal(e.status, 429)
      assert.equal(e.code, 'rate_limited')
      assert.equal(e.message, 'Slow down')
      assert.equal(e.retryAfter, 7)
      return true
    })
  } finally {
    s.close()
  }
})

test('non-JSON error still throws', async () => {
  const s = await serve(502, '<html>bad</html>', { 'Content-Type': 'text/html' })
  try {
    await assert.rejects(new Agent({ apiKey: 'k', baseUrl: s.url }).run('hi'), (e) => {
      assert.ok(e instanceof AgentError)
      assert.equal(e.status, 502)
      assert.equal(e.code, 'http_error')
      assert.equal(e.retryAfter, null)
      return true
    })
  } finally {
    s.close()
  }
})

test('trailing slash in baseUrl', async () => {
  const s = await serve(200, { reply: 'ok' })
  try {
    await new Agent({ apiKey: 'k', baseUrl: s.url + '/' }).run('hi')
    assert.equal(s.seen.path, '/v1/run')
  } finally {
    s.close()
  }
})

test('string detail falls back to the generic error', async () => {
  const s = await serve(404, { detail: 'Not Found' })
  try {
    await assert.rejects(new Agent({ apiKey: 'k', baseUrl: s.url }).run('hi'), (e) => {
      assert.ok(e instanceof AgentError)
      assert.equal(e.code, 'http_error')
      assert.equal(e.message, 'HTTP 404')
      return true
    })
  } finally {
    s.close()
  }
})
