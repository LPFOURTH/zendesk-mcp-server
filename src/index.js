#!/usr/bin/env node
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { server } from './server.js';
import { runWithAuth } from './zendesk-client.js';
import dotenv from 'dotenv';
import http from 'node:http';
import { URL } from 'node:url';
import { randomUUID } from 'node:crypto';

dotenv.config();

const transport = process.env.MCP_TRANSPORT || (process.argv.includes('--transport') ?
  process.argv[process.argv.indexOf('--transport') + 1] : 'stdio');

if (transport === 'http' || transport === 'sse') {
  const port = parseInt(process.env.MCP_HTTP_PORT, 10) || 8000;
  const host = process.env.MCP_HTTP_HOST || '0.0.0.0';

  const sseSessions = new Map();

  const streamableSessions = new Map();

  const healthResponse = JSON.stringify({
    status: 'healthy',
    service: 'Zendesk MCP Server',
    version: '1.2.0',
    transports: ['sse', 'streamable-http']
  });

  async function readBody(req) {
    const chunks = [];
    for await (const chunk of req) { chunks.push(chunk); }
    return Buffer.concat(chunks).toString();
  }

  const httpServer = http.createServer(async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`);
    const authHeader = req.headers['authorization'] || null;

    // ── Health ──────────────────────────────────────────────────────
    if (req.method === 'GET' && (url.pathname === '/' || url.pathname === '/health')) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(healthResponse);
      return;
    }

    // ── Streamable HTTP transport (POST /mcp) — CoPilot Studio ─────
    if (url.pathname === '/mcp') {
      const sessionId = req.headers['mcp-session-id'];

      if (req.method === 'POST') {
        const raw = await readBody(req);
        console.error(`[zendesk-mcp] POST /mcp (session: ${sessionId || 'new'}): ${raw.substring(0, 200)}`);
        const body = JSON.parse(raw);

        const isInit = Array.isArray(body)
          ? body.some(m => m.method === 'initialize')
          : body.method === 'initialize';

        if (isInit && !sessionId) {
          const streamTransport = new StreamableHTTPServerTransport({
            sessionIdGenerator: () => randomUUID(),
          });

          streamTransport.onclose = () => {
            const sid = streamTransport.sessionId;
            if (sid) streamableSessions.delete(sid);
            console.error(`[zendesk-mcp] Streamable session closed: ${sid}`);
          };

          await server.connect(streamTransport);

          if (streamTransport.sessionId) {
            streamableSessions.set(streamTransport.sessionId, { transport: streamTransport, authHeader });
          }

          await runWithAuth(authHeader, () => streamTransport.handleRequest(req, res, body));
          return;
        }

        const session = streamableSessions.get(sessionId);
        if (!session) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Invalid or missing session. Send initialize first.' }));
          return;
        }

        if (authHeader) session.authHeader = authHeader;

        await runWithAuth(session.authHeader, () => session.transport.handleRequest(req, res, body));
        return;
      }

      if (req.method === 'GET') {
        const session = streamableSessions.get(sessionId);
        if (!session) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Invalid or missing session.' }));
          return;
        }
        await session.transport.handleRequest(req, res);
        return;
      }

      if (req.method === 'DELETE') {
        const session = streamableSessions.get(sessionId);
        if (session) {
          await session.transport.close();
          streamableSessions.delete(sessionId);
        }
        res.writeHead(200);
        res.end();
        return;
      }
    }

    // ── Legacy SSE transport (GET /sse + POST /messages) ────────────
    if (req.method === 'GET' && url.pathname === '/sse') {
      console.error(`[zendesk-mcp] SSE connection from ${req.socket.remoteAddress}`);
      const sseTransport = new SSEServerTransport('/messages', res);
      sseSessions.set(sseTransport.sessionId, { transport: sseTransport, authHeader });

      res.on('close', () => {
        sseSessions.delete(sseTransport.sessionId);
        console.error(`[zendesk-mcp] SSE session closed: ${sseTransport.sessionId}`);
      });

      await server.connect(sseTransport);
      return;
    }

    if (req.method === 'POST' && url.pathname === '/messages') {
      const sessionId = url.searchParams.get('sessionId');
      const session = sseSessions.get(sessionId);
      if (!session) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Invalid or expired session ID' }));
        return;
      }

      if (authHeader) session.authHeader = authHeader;

      try {
        const raw = await readBody(req);
        console.error(`[zendesk-mcp] POST /messages body: ${raw.substring(0, 200)}`);
        const body = JSON.parse(raw);
        await runWithAuth(session.authHeader, () =>
          session.transport.handlePostMessage(req, res, body)
        );
      } catch (err) {
        console.error(`[zendesk-mcp] POST error: ${err.message}`);
        if (!res.headersSent) {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: err.message }));
        }
      }
      return;
    }

    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
  });

  httpServer.listen(port, host, () => {
    console.error(`[zendesk-mcp] HTTP server listening on ${host}:${port}`);
    console.error(`[zendesk-mcp] Streamable HTTP: http://${host}:${port}/mcp`);
    console.error(`[zendesk-mcp] Legacy SSE:      http://${host}:${port}/sse`);
    console.error(`[zendesk-mcp] Health check:     http://${host}:${port}/health`);
  });

} else {
  console.error('[zendesk-mcp] Starting in stdio mode...');
  const stdioTransport = new StdioServerTransport();
  await server.connect(stdioTransport);
}
