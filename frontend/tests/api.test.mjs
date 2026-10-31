import assert from 'node:assert/strict'
import test from 'node:test'

import { api } from '../src/api.js'

test('returns JSON and sends POST data to the API prefix', async t => {
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/requirements')
    assert.equal(options.method, 'POST')
    assert.deepEqual(JSON.parse(options.body), { qty: 200 })
    return Response.json({ id: 1 })
  })
  assert.deepEqual(await api('/requirements', { qty: 200 }), { id: 1 })
})

test('shows field paths from a validation response', async t => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({
    detail: [{ loc: ['body', 'qty'], msg: 'Must be positive' }],
  }, { status: 422 }))
  await assert.rejects(api('/requirements', { qty: 0 }), /qty: Must be positive/)
})

test('reports an HTML gateway error without showing its response body', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>upstream error</html>', { status: 502 }))
  await assert.rejects(api('/health'), error => {
    assert.match(error.message, /HTTP 502/)
    assert.doesNotMatch(error.message, /<html>|Unexpected token/)
    return true
  })
})

test('accepts an empty 204 response', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(null, { status: 204 }))
  assert.equal(await api('/requirements/1', {}, 'DELETE'), undefined)
})

test('reports a non-JSON success response as an API configuration error', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>frontend page</html>', { status: 200 }))
  await assert.rejects(api('/materials'), /Expected JSON.*HTTP 200/)
})

test('uses HTTP status when a JSON error has no detail', async t => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({}, { status: 503 }))
  await assert.rejects(api('/health'), /Request failed \(503\)/)
})
