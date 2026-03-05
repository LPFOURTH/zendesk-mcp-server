import { McpServer, ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js';
import { ticketsTools } from './tools/tickets.js';
import { helpCenterTools } from './tools/help-center.js';
import { searchTools } from './tools/search.js';
import { releaseNotesTools } from './tools/release-notes.js';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));

function loadToolsConfig() {
  const configPath = process.env.TOOLS_CONFIG || resolve(__dirname, '..', 'tools.config.json');
  try {
    const raw = readFileSync(configPath, 'utf-8');
    const config = JSON.parse(raw);

    const preset = process.env.TOOLS_PRESET;
    if (preset && config.presets?.[preset]) {
      const p = config.presets[preset];
      console.error(`[zendesk-mcp] Using preset: ${preset} — ${p._description}`);
      const disabled = new Set(p.disable || []);
      const enabled = new Set(p.enable || []);
      return { enabled, disabled, source: `preset:${preset}` };
    }

    const disabled = new Set();
    const enabled = new Set();
    for (const [name, cfg] of Object.entries(config.tools || {})) {
      if (cfg.enabled === false) {
        disabled.add(name);
      } else {
        enabled.add(name);
      }
    }
    return { enabled, disabled, source: configPath };
  } catch (err) {
    console.error(`[zendesk-mcp] No tools.config.json found (${err.message}), using defaults`);
    return { enabled: null, disabled: new Set(), source: 'defaults' };
  }
}

const server = new McpServer({
  name: "Zendesk API",
  version: "1.2.0",
  description: "Hardened MCP Server for Zendesk API - Tickets & Articles (read/create/update only, no delete operations)"
});

const allTools = [
  ...ticketsTools,
  ...helpCenterTools,
  ...searchTools,
  ...releaseNotesTools
];

const config = loadToolsConfig();

const envDisabled = new Set(
  (process.env.DISABLED_TOOLS || '').split(',').map(t => t.trim()).filter(Boolean)
);
for (const t of envDisabled) config.disabled.add(t);

const enabledTools = allTools.filter(tool => {
  if (config.disabled.has(tool.name)) return false;
  if (config.enabled && !config.enabled.has(tool.name)) return false;
  return true;
});

enabledTools.forEach(tool => {
  const args = [tool.name, tool.description, tool.schema];
  if (tool.annotations) args.push(tool.annotations);
  args.push(tool.handler);
  server.tool(...args);
});

console.error(`[zendesk-mcp] Config source: ${config.source}`);
console.error(`[zendesk-mcp] Registered ${enabledTools.length}/${allTools.length} tools: ${enabledTools.map(t => t.name).join(', ')}`);
if (config.disabled.size > 0) {
  console.error(`[zendesk-mcp] Disabled: ${[...config.disabled].join(', ')}`);
}

server.resource(
  "documentation",
  new ResourceTemplate("zendesk://docs/{section}", { list: undefined }),
  async (uri, { section }) => {
    const docs = {
      "tickets": "Tickets API: list, get, create, update tickets.\nEndpoints: GET/POST/PUT /api/v2/tickets",
      "help_center": "Help Center API: list, get, create, update articles.\nEndpoints: GET/POST/PUT /api/v2/help_center/articles",
      "search": "Search API: search across Zendesk data.\nEndpoints: GET /api/v2/search",
      "overview": "This server provides access to Zendesk Tickets and Help Center Articles (read/create/update). All delete operations have been removed for safety."
    };

    if (!section || section === "all") {
      return {
        contents: [{
          uri: uri.href,
          text: `Zendesk API Documentation Overview\n\n${Object.keys(docs).map(key => `- ${key}: ${docs[key].split('\n')[0]}`).join('\n')}`
        }]
      };
    }

    if (docs[section]) {
      return {
        contents: [{
          uri: uri.href,
          text: `Zendesk API Documentation: ${section}\n\n${docs[section]}`
        }]
      };
    }

    return {
      contents: [{
        uri: uri.href,
        text: `Section '${section}' not found. Available: ${Object.keys(docs).join(', ')}`
      }]
    };
  }
);

export { server };
