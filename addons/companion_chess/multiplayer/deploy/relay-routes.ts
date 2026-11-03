/** Install as apps/relay-api/src/chess/routes.ts. Chess-only gateway, not signaling. */
import { readFileSync } from "node:fs";
import type { AppInstance } from "../types.js";
import type { Container } from "../container.js";
import { authContext, requireAuth } from "../auth/guards.js";
import { RateLimitBucket, enforceRateLimit } from "../security/rate-limit.js";
import { ApiError } from "../errors.js";
import { ApiErrorCode } from "@nc-relay/protocol";

export function registerChessRoutes(app: AppInstance, deps: Pick<Container, "auth" | "tokens" | "desktops" | "rateLimiter">): void {
  let gatewayKey = "";
  if (process.env.NC_CHESS_ENABLED === "1") {
    try {
      gatewayKey = readFileSync(process.env.NC_CHESS_GATEWAY_KEY_FILE || "/run/secrets/chess_gateway_key", "utf8").trim();
    } catch { /* Only chess becomes unavailable; do not break relay startup. */ }
  }
  app.post("/v1/chess/mcp", { preHandler: requireAuth(deps.tokens, ["desktop"]) }, async (request, reply) => {
    if (gatewayKey.length < 32 || gatewayKey.length > 256) {
      return reply.code(503).send({ error: { code: "CHESS_UNAVAILABLE", message: "Online chess is not enabled" } });
    }
    const identity = authContext(request);
    const registration = await deps.desktops.getCurrent(identity.sub);
    if (!registration || !identity.desktopId || registration.desktopId !== identity.desktopId) {
      throw new ApiError(ApiErrorCode.Forbidden, "This desktop registration is no longer current");
    }
    await enforceRateLimit(deps.rateLimiter, RateLimitBucket.Signaling, "chess:" + identity.sub, 120, 60);
    const account = await deps.auth.getAccount(identity.sub);
    const body = request.body as Record<string, unknown> | null;
    const params = body?.params as Record<string, unknown> | undefined;
    if (!body || body.jsonrpc !== "2.0" || body.method !== "tools/call" || typeof body.id !== "string"
        || body.id.length > 128 || !params || typeof params.name !== "string"
        || !/^(chess_lobby_|chess_online_)[a-z_]+$/.test(params.name)
        || !params.arguments || typeof params.arguments !== "object" || Array.isArray(params.arguments)) {
      throw ApiError.validation("Invalid online chess tool call");
    }
    const meta=params._meta as Record<string,unknown> | undefined;
    if (params.name !== "chess_lobby_status" && (!meta || meta.expectedAccount !== identity.sub)) {
      throw new ApiError(ApiErrorCode.Forbidden, "Chess account changed; synchronize first");
    }
    const payload = JSON.stringify({ jsonrpc: "2.0", id: body.id, method: "tools/call",
      params: { name: params.name, arguments: params.arguments } });
    if (Buffer.byteLength(payload) > 65536) throw ApiError.validation("Chess request is too large");
    try {
      // Fixed private destination and freshly constructed headers. Never forward
      // the user's JWT, account headers, cookies, URL, or arbitrary MCP methods.
      const response = await fetch("http://chess-mcp:8767/mcp", {
        method: "POST", redirect: "error", signal: AbortSignal.timeout(8000),
        headers: { "content-type": "application/json", "authorization": "Bearer " + gatewayKey,
          "x-nc-account": account.id, "x-nc-username": account.username }, body: payload,
      });
      if (!response.ok || !response.body) throw new Error("upstream unavailable");
      const reader = response.body.getReader();
      const chunks: Uint8Array[] = []; let size = 0;
      try {
        for (;;) {
          const item = await reader.read(); if (item.done) break;
          size += item.value.length;
          if (size > 524288) throw new Error("response too large");
          chunks.push(item.value);
        }
      } finally { await reader.cancel().catch(() => {}); }
      const result: unknown = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      return reply.header("Cache-Control", "no-store").send(result);
    } catch {
      return reply.code(503).send({ error: { code: "CHESS_UNAVAILABLE", message: "Online chess unavailable; retry the same operation" } });
    }
  });
}
