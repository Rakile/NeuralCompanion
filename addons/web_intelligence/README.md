# Web Search / Web Intelligence

For the current UI walkthrough, use [Web Search](../../docs/addons/web_search.md). Configure search under **Addons → Web Search**; the technical provider and optional external-server details below remain available.

This addon injects current search evidence into NC's existing normal-chat prompt
pipeline. It does not replace the selected LLM provider and does not modify the
core runtime.

The default provider chain is:

1. `mcp_searxng` at `http://127.0.0.1:3000/mcp`
2. `duckduckgo_mcp` at `http://127.0.0.1:8000/mcp`

Both servers use Streamable HTTP mode. NC never installs or starts them silently.
The native **Web Search** addon tab includes an explicit **Install / repair search
servers** action. It installs DuckDuckGo MCP into an addon-private Python virtual
environment and, when Node.js/npm is available, installs the SearXNG MCP bridge
into addon-private Node storage. Installation is supervised in the background,
can be cancelled during addon shutdown, and opens no terminal windows. The tab
can then start the local servers, check endpoint readiness, stop only processes
that NC started, and run a one-result diagnostic search. An endpoint started
outside NC is detected and left under external ownership. The default `auto`
mode searches freshness-sensitive requests; `/web <question>` requests a one-turn
search when the global switch and Conversation mode allow it.

Installed packages are stored below
`runtime/addons/nc.web_intelligence/search_servers`; they do not modify NC's
Python environment. The SearXNG MCP package is a bridge and still needs an
operator-provided SearXNG search instance at `SEARXNG_URL` (by default
`http://127.0.0.1:8080`). DuckDuckGo MCP is the no-key, self-contained fallback.

## Optional manual startup on Windows

Use these commands only if you prefer externally managed servers. `mcp-searxng`
also requires a running SearXNG instance. In PowerShell:

```powershell
$env:MCP_HTTP_PORT = "3000"
$env:SEARXNG_URL = "http://127.0.0.1:8080"
npx -y mcp-searxng
```

In a second PowerShell window, start DuckDuckGo MCP with its recommended browser
fallback:

```powershell
uvx --with "duckduckgo-mcp-server[browser]" duckduckgo-mcp-server `
  --transport streamable-http --host 127.0.0.1 --port 8000
```

Keep both endpoints loopback-only for this local test.

Commands:

- `/web status`
- `/web auto`
- `/web always`
- `/web off`
- `/web clear-cache`
- `/web <question>`

Optional environment settings include:

- `NC_WEB_PROVIDERS=mcp_searxng,duckduckgo_mcp`
- `NC_MCP_SEARXNG_URL=http://127.0.0.1:3000/mcp`
- `NC_MCP_DUCKDUCKGO_URL=http://127.0.0.1:8000/mcp`
- `NC_MCP_DUCKDUCKGO_REGION=wt-wt`
- `NC_WEB_MAX_RESULTS`, `NC_WEB_FETCH_PAGES`, `NC_WEB_TIMEOUT_SECONDS`
- `NC_WEB_SEARCH_LANGUAGE`

The old Brave adapter remains available only as an explicit optional fallback
(`NC_WEB_PROVIDERS=...,...,brave`). API keys and MCP endpoint URLs are never
stored in presets or session data.

## Global enable switch

**Overview > Enable web search** takes effect immediately and is saved with addon
session and preset state. Turning it off blocks all search-intent model calls,
normal-chat and LocalRoom searches, explicit `/web` queries, and diagnostic test
searches. It preserves the Conversation search mode, provider configuration and
running search servers. Server installation, endpoint checks, and start/stop
controls remain available. Re-enable the switch to restore the saved mode.
Older saved state defaults to enabled, preserving existing behavior.

The Conversation mode still selects `off`, `auto`, or `always`. Conversation
`off` also blocks explicit `/web` queries. The global switch does not change this
mode; both gates must allow a normal-chat search.
Automatic LLM intent classification is skipped when no configured search backend
is known to be online; this uses cached readiness and does not probe endpoints.
