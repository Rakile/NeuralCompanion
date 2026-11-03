# Relay deployment staging — Python 3.11

These are the reproducible deployment sources. On 2026-10-28 the relay was
updated to nc-relay-api:chess-20261028 and the private chess-mcp service to
nc-chess-mcp:20261028 (Python 3.11.18). Both reported healthy. Previous image and
source/config backups remain available. A real two-account desktop match still
requires live verification; automated two-player and gateway boundary tests pass.

1. Copy `relay-routes.ts` to the relay source's `apps/relay-api/src/chess/routes.ts`.
2. Add `import { registerChessRoutes } from './chess/routes.js'` to `src/app.ts` and
   `registerChessRoutes(app, container)` alongside the existing route registration.
3. Build/test the relay image before enabling the route. Existing signaling and
   authentication contracts are unchanged. The new route only accepts desktop
   sessions with a current registration, and forwards verified ID/username only.
4. Build the multiplayer Dockerfile with context `addons/companion_chess`.
   It pins Python 3.11 and uses existing chess/jsonschema libraries. Run a
   `chess-mcp` service on the private backend network, **without publishing ports**.
   Its separate `/data` volume contains only `online.sqlite3` and SQLite WAL files.
5. Generate a new random gateway key on the server, never in the repository.
   Mount the same read-only key file in both services at
   `/run/secrets/chess_gateway_key`. Set `NC_CHESS_GATEWAY_KEY_FILE` in both;
   set `NC_CHESS_ENABLED=1` only in the relay API after validation.
6. Verify isolated chess health, schema and two-account authorization tests,
   backup the existing deployment files/image and activate the chess service and
   gateway. A short relay-api restart may affect active Internet sessions; do
   not restart unrelated Caddy, TURN, PostgreSQL or Redis services.

Include the gateway tests during the relay build (the old .dockerignore excluded
all tests). Exclude chess-source from the relay image build context, and exclude
gateway-key from the Python image build context. The live key is server-only,
mode 0640, owned by the existing codex group 986. Both services receive group 986
as a supplemental group for this read-only mount; no key is embedded in an image.

Rollback: disable NC_CHESS_ENABLED or restore the previous relay API image and
configuration. Keep the online volume; local single-player files are not touched.

The 0.0.0.0 listener requires `--private-container-network` explicitly. This is
only for the isolated Docker network and must never be mapped to a public port.
Default execution binds 127.0.0.1. The gateway upstream is fixed to chess-mcp:8767,
not supplied by players; internal bearer/identity headers are constructed afresh.
