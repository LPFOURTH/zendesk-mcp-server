#!/usr/bin/env node
'use strict';

/**
 * MCP proxy launcher for the Fourth Zendesk MCP Extension.
 *
 * Invoked by Claude Desktop's bundled Node.js (command: "node" in manifest).
 * No credentials needed — the server handles OAuth via AzureProvider (Entra SSO).
 *
 * Based on the rally-mcp-server extension pattern (v1.0.15).
 *
 * Design decisions (from Rally team's battle-tested experience):
 *   - command: "node" (not "npx") → Claude Desktop's bundled Node has a spaces-free path
 *   - stdio: pipe + readline → prevents batched JSON-RPC messages
 *   - findNpx() → Claude Desktop runs with stripped PATH on macOS
 *   - shell:true on Windows → single command string survives cmd.exe quoting
 *   - windowsHide:true → suppresses cmd.exe console window in Electron GUI
 */

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');
const readline = require('readline');

// The /mcp/dev path uses Entra OAuth (AzureProvider handles the flow).
// No credentials needed in this proxy — the MCP protocol OAuth dance
// happens between Claude Desktop and the server directly.
const SERVER_URL = 'https://fourth-zendesk-mcp-server.bluewave-95f931ef.northeurope.azurecontainerapps.io/mcp/dev/mcp';

/**
 * Find npx on macOS/Linux where Claude Desktop Plugin runs with stripped PATH.
 * Searches NVM versions and Homebrew without invoking a shell.
 */
function findNpx() {
  const home = os.homedir();
  const candidates = [];

  // NVM: iterate installed versions latest-first
  try {
    const nvmVersionsDir = path.join(home, '.nvm', 'versions', 'node');
    fs.readdirSync(nvmVersionsDir)
      .filter(v => /^v\d/.test(v))
      .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))
      .forEach(v => candidates.push(path.join(nvmVersionsDir, v, 'bin', 'npx')));
  } catch {}

  // Homebrew (Apple Silicon and Intel)
  candidates.push('/opt/homebrew/bin/npx', '/usr/local/bin/npx');

  for (const c of candidates) {
    try { fs.accessSync(c, fs.constants.X_OK); return c; } catch {}
  }
  return 'npx'; // fallback — will ENOENT if still not found
}

let child;

if (process.platform === 'win32') {
  // Windows: single command string + shell:true
  // cmd.exe's /s flag strips outer quotes; inner quotes survive for mcp-remote args
  const shellCmd = `npx -y mcp-remote ${SERVER_URL}`;
  child = spawn(shellCmd, [], {
    shell: true,
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
  });
} else {
  // macOS/Linux: find npx, augment PATH so node is discoverable
  const npxPath = findNpx();
  const npxBinDir = path.dirname(npxPath);
  const augmentedPath = `${npxBinDir}:${process.env.PATH || '/usr/bin:/bin:/usr/sbin:/sbin'}`;
  child = spawn(
    npxPath,
    ['-y', 'mcp-remote', SERVER_URL],
    {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PATH: augmentedPath },
    }
  );
}

// Pipe stdin from Claude Desktop → mcp-remote
process.stdin.pipe(child.stdin);

// Write each JSON-RPC line separately so Claude Desktop never receives
// two messages in a single pipe chunk (which it fails to parse).
const rl = readline.createInterface({ input: child.stdout, crlfDelay: Infinity });
rl.on('line', (line) => { if (line) process.stdout.write(line + '\n'); });
child.stderr.on('data', () => {});

child.on('error', (err) => {
  process.stderr.write(`Failed to start mcp-remote: ${err.message}\n`);
  process.exit(1);
});

child.on('exit', (code, signal) => {
  process.exit(code ?? (signal ? 1 : 0));
});
