# Claude Desktop MCP Extensions

Extensions for connecting Claude Desktop to Fourth's Zendesk MCP Server.

## Available Extension

### fourth-zendesk-mcp-extension
- **Server URL:** `https://fourth-zendesk-mcp-server.bluewave-95f931ef.northeurope.azurecontainerapps.io/mcp/dev/mcp`
- **Version:** 1.0.0
- **Auth:** Entra SSO via AzureProvider (no credentials needed in extension — OAuth handled by mcp-remote)
- **Tools:** 10 (list/get/create/update tickets, list/get/create/update articles, search, release notes)

## How It Works

1. User installs the extension in Claude Desktop
2. Claude Desktop launches `proxy.js` via its bundled Node.js
3. `proxy.js` spawns `npx mcp-remote` to connect to the remote server
4. `mcp-remote` performs the MCP OAuth dance (DCR → authorize → Entra SSO → token)
5. All MCP protocol messages are proxied between Claude Desktop and the server

## Installation (For Fourth Team Members)

### From Anthropic Directory

1. Open Claude Desktop
2. Go to **Settings** → **Connectors** → **Browse connectors** → **Desktop extensions**
3. Search for "**zendesk**"
4. Click **Install**
5. Restart Claude Desktop

### From File

1. Get the `.mcpb` file from the team
2. In Claude Desktop: Settings → Connectors → **Install from file**
3. Select the `.mcpb` file
4. Restart Claude Desktop

## Building

```bash
npm install -g @anthropic-ai/mcpb
cd claude-zendesk-mcp-extensions/fourth-zendesk-mcp-extension
mcpb pack
```

**Never use `zip`** — `mcpb pack` validates the manifest schema.

## Releasing a New Version

1. Edit `manifest.json` and/or `proxy.js`
2. Bump `version` in `manifest.json`
3. Run `mcpb pack`
4. Commit including the new `.mcpb`
5. Submit to Anthropic directory if published

## Troubleshooting

### macOS: "npx not found"

Claude Desktop runs with a stripped PATH. The `proxy.js` scans common locations (`~/.nvm/versions/`, `/opt/homebrew/bin`, `/usr/local/bin`). If npx is installed elsewhere, update `findNpx()` in `proxy.js`.

### Windows: "Server disconnected"

Ensure Node.js is installed from [nodejs.org](https://nodejs.org/). Restart Claude Desktop after installation.

## See Also

- [Rally MCP extensions](https://github.com/fourth/rally-mcp-server/tree/main/claude-rally-mcp-extensions) — reference implementation
