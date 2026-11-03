import { z } from "zod";

/**
 * NC Relay signaling protocol.
 *
 * The protocol is versioned from its first release. Every message carries a
 * literal `v` field; a receiver must reject any message whose version it does
 * not implement instead of guessing.
 *
 * Wire format notes:
 * - `hello` travels in both directions. A client sends it with an empty
 *   `connectionId` string; the server always ignores whatever the client put
 *   there and replies with the server-generated connection ID. Clients cannot
 *   choose, reuse, or impersonate a connection ID.
 * - `offer`, `answer`, `ice-candidate` and `hangup` are only ever forwarded
 *   between two authenticated connections that belong to the same account and
 *   are bound to the same signaling session.
 * - SDP bodies and ICE payloads are forwarded verbatim and are never logged.
 */

export const SIGNALING_PROTOCOL_VERSION = 1 as const;

export const SignalingVersionSchema = z.literal(SIGNALING_PROTOCOL_VERSION);

export const CLIENT_ROLES = ["desktop", "mobile"] as const;
export type ClientRole = (typeof CLIENT_ROLES)[number];
export const ClientRoleSchema = z.enum(CLIENT_ROLES);

export const SIGNALING_MESSAGE_TYPES = [
  "hello",
  "desktop-presence",
  "offer",
  "answer",
  "ice-candidate",
  "hangup",
  "error",
] as const;
export type SignalingMessageType = (typeof SIGNALING_MESSAGE_TYPES)[number];

/** Ceiling applied to the raw UTF-8 byte length of an inbound message. */
export const DEFAULT_MAX_SIGNALING_MESSAGE_BYTES = 64 * 1024;
/** Ceiling applied to a single SDP body. */
export const DEFAULT_MAX_SDP_BYTES = 48 * 1024;
/** Ceiling applied to a serialized ICE candidate. */
export const DEFAULT_MAX_CANDIDATE_BYTES = 4 * 1024;
/** Ceiling for opaque identifiers supplied by peers. */
export const MAX_IDENTIFIER_LENGTH = 128;

export const MAX_SESSION_ID_LENGTH = MAX_IDENTIFIER_LENGTH;
export const MAX_DESKTOP_ID_LENGTH = MAX_IDENTIFIER_LENGTH;
export const MAX_CONNECTION_ID_LENGTH = MAX_IDENTIFIER_LENGTH;

const version = { v: SignalingVersionSchema };

export const HelloMessageSchema = z
  .object({
    v: version.v,
    type: z.literal("hello"),
    role: ClientRoleSchema,
    connectionId: z.string().max(MAX_CONNECTION_ID_LENGTH),
  })
  .strict();

export const DesktopPresenceMessageSchema = z
  .object({
    v: version.v,
    type: z.literal("desktop-presence"),
    online: z.boolean(),
    desktopId: z.string().min(1).max(MAX_DESKTOP_ID_LENGTH),
  })
  .strict();

const sessionScoped = {
  sessionId: z.string().min(1).max(MAX_SESSION_ID_LENGTH),
  targetRole: ClientRoleSchema,
};

export const OfferMessageSchema = z
  .object({
    v: version.v,
    type: z.literal("offer"),
    ...sessionScoped,
    sdp: z.string().min(1),
  })
  .strict();

export const AnswerMessageSchema = z
  .object({
    v: version.v,
    type: z.literal("answer"),
    ...sessionScoped,
    sdp: z.string().min(1),
  })
  .strict();

export const IceCandidateMessageSchema = z
  .object({
    v: version.v,
    type: z.literal("ice-candidate"),
    ...sessionScoped,
    candidate: z.record(z.string(), z.unknown()),
  })
  .strict();

export const HangupMessageSchema = z
  .object({
    v: version.v,
    type: z.literal("hangup"),
    ...sessionScoped,
    reason: z.string().min(1).max(256),
  })
  .strict();

export const ErrorMessageSchema = z
  .object({
    v: version.v,
    type: z.literal("error"),
    code: z.string().min(1).max(64),
    message: z.string().min(1).max(512),
    sessionId: z.string().min(1).max(MAX_SESSION_ID_LENGTH).optional(),
  })
  .strict();

export const SignalingMessageSchema = z.discriminatedUnion("type", [
  HelloMessageSchema,
  DesktopPresenceMessageSchema,
  OfferMessageSchema,
  AnswerMessageSchema,
  IceCandidateMessageSchema,
  HangupMessageSchema,
  ErrorMessageSchema,
]);

export type SignalingMessage = z.infer<typeof SignalingMessageSchema>;
export type HelloMessage = z.infer<typeof HelloMessageSchema>;
export type DesktopPresenceMessage = z.infer<typeof DesktopPresenceMessageSchema>;
export type OfferMessage = z.infer<typeof OfferMessageSchema>;
export type AnswerMessage = z.infer<typeof AnswerMessageSchema>;
export type IceCandidateMessage = z.infer<typeof IceCandidateMessageSchema>;
export type HangupMessage = z.infer<typeof HangupMessageSchema>;
export type ErrorMessage = z.infer<typeof ErrorMessageSchema>;

/** Messages that are only valid once bound to a signaling session. */
export const SESSION_SCOPED_MESSAGE_TYPES = ["offer", "answer", "ice-candidate", "hangup"] as const;
export type SessionScopedMessageType = (typeof SESSION_SCOPED_MESSAGE_TYPES)[number];

export type SessionScopedMessage = Extract<
  SignalingMessage,
  { type: SessionScopedMessageType }
>;

export function isSessionScopedMessage(
  message: SignalingMessage,
): message is SessionScopedMessage {
  return (SESSION_SCOPED_MESSAGE_TYPES as readonly string[]).includes(message.type);
}

/** Application-level rejection codes exchanged over the signaling socket. */
export const SignalingErrorCode = {
  UnsupportedVersion: "UNSUPPORTED_VERSION",
  UnknownMessageType: "UNKNOWN_MESSAGE_TYPE",
  InvalidMessage: "INVALID_MESSAGE",
  MessageTooLarge: "MESSAGE_TOO_LARGE",
  RateLimited: "RATE_LIMITED",
  NotAuthenticated: "NOT_AUTHENTICATED",
  WrongRole: "WRONG_ROLE",
  DesktopMismatch: "DESKTOP_MISMATCH",
  UnknownSession: "UNKNOWN_SESSION",
  SessionTakenOver: "SESSION_TAKEN_OVER",
  PeerOffline: "PEER_OFFLINE",
  InternalError: "INTERNAL_ERROR",
} as const;
export type SignalingErrorCode =
  (typeof SignalingErrorCode)[keyof typeof SignalingErrorCode];

export type SignalingParseErrorCode =
  | "MESSAGE_TOO_LARGE"
  | "INVALID_JSON"
  | "UNSUPPORTED_VERSION"
  | "UNKNOWN_MESSAGE_TYPE"
  | "INVALID_MESSAGE";

export interface SignalingParseError {
  code: SignalingParseErrorCode;
  message: string;
  sessionId?: string;
}

export type SignalingParseResult =
  | { ok: true; message: SignalingMessage; bytes: number }
  | { ok: false; error: SignalingParseError; bytes: number };

export interface ParseSignalingOptions {
  /** Raw UTF-8 byte ceiling for the whole message. */
  maxBytes?: number;
  /** Raw UTF-8 byte ceiling for an SDP body. */
  maxSdpBytes?: number;
  /** Raw UTF-8 byte ceiling for a serialized ICE candidate. */
  maxCandidateBytes?: number;
}

export function utf8ByteLength(value: string): number {
  return Buffer.byteLength(value, "utf8");
}

/**
 * Parse and validate an inbound signaling frame.
 *
 * Size is enforced on the raw bytes *before* JSON.parse so a hostile peer
 * cannot force a large allocation by sending an oversized frame.
 */
export function parseSignalingMessage(
  raw: string | Buffer,
  options: ParseSignalingOptions = {},
): SignalingParseResult {
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_SIGNALING_MESSAGE_BYTES;
  const maxSdpBytes = options.maxSdpBytes ?? DEFAULT_MAX_SDP_BYTES;
  const maxCandidateBytes = options.maxCandidateBytes ?? DEFAULT_MAX_CANDIDATE_BYTES;

  const text = typeof raw === "string" ? raw : raw.toString("utf8");
  const bytes = utf8ByteLength(text);

  if (bytes > maxBytes) {
    return {
      ok: false,
      bytes,
      error: {
        code: "MESSAGE_TOO_LARGE",
        message: `Signaling message exceeds ${maxBytes} bytes`,
      },
    };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return {
      ok: false,
      bytes,
      error: { code: "INVALID_JSON", message: "Signaling message is not valid JSON" },
    };
  }

  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return {
      ok: false,
      bytes,
      error: { code: "INVALID_MESSAGE", message: "Signaling message must be a JSON object" },
    };
  }

  const record = parsed as Record<string, unknown>;

  if (record["v"] !== SIGNALING_PROTOCOL_VERSION) {
    return {
      ok: false,
      bytes,
      error: {
        code: "UNSUPPORTED_VERSION",
        message: `Signaling protocol version ${SIGNALING_PROTOCOL_VERSION} is required`,
      },
    };
  }

  const type = record["type"];
  if (
    typeof type !== "string" ||
    !(SIGNALING_MESSAGE_TYPES as readonly string[]).includes(type)
  ) {
    return {
      ok: false,
      bytes,
      error: { code: "UNKNOWN_MESSAGE_TYPE", message: "Unknown signaling message type" },
    };
  }

  const result = SignalingMessageSchema.safeParse(record);
  if (!result.success) {
    const sessionId = typeof record["sessionId"] === "string" ? record["sessionId"] : undefined;
    return {
      ok: false,
      bytes,
      error: {
        code: "INVALID_MESSAGE",
        message: "Signaling message failed schema validation",
        ...(sessionId ? { sessionId } : {}),
      },
    };
  }

  const message = result.data;

  if (message.type === "offer" || message.type === "answer") {
    if (utf8ByteLength(message.sdp) > maxSdpBytes) {
      return {
        ok: false,
        bytes,
        error: {
          code: "MESSAGE_TOO_LARGE",
          message: `SDP body exceeds ${maxSdpBytes} bytes`,
          sessionId: message.sessionId,
        },
      };
    }
  }

  if (message.type === "ice-candidate") {
    if (utf8ByteLength(JSON.stringify(message.candidate)) > maxCandidateBytes) {
      return {
        ok: false,
        bytes,
        error: {
          code: "MESSAGE_TOO_LARGE",
          message: `ICE candidate exceeds ${maxCandidateBytes} bytes`,
          sessionId: message.sessionId,
        },
      };
    }
  }

  return { ok: true, message, bytes };
}

/** Serialize a server-originated message. Callers must never log the result. */
export function serializeSignalingMessage(message: SignalingMessage): string {
  return JSON.stringify(message);
}

export function signalingErrorMessage(
  code: string,
  message: string,
  sessionId?: string,
): ErrorMessage {
  return {
    v: SIGNALING_PROTOCOL_VERSION,
    type: "error",
    code,
    message,
    ...(sessionId ? { sessionId } : {}),
  };
}
