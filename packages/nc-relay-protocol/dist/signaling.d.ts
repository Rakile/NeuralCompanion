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
export declare const SIGNALING_PROTOCOL_VERSION: 1;
export declare const SignalingVersionSchema: z.ZodLiteral<1>;
export declare const CLIENT_ROLES: readonly ["desktop", "mobile"];
export type ClientRole = (typeof CLIENT_ROLES)[number];
export declare const ClientRoleSchema: z.ZodEnum<{
    desktop: "desktop";
    mobile: "mobile";
}>;
export declare const SIGNALING_MESSAGE_TYPES: readonly ["hello", "desktop-presence", "offer", "answer", "ice-candidate", "hangup", "error"];
export type SignalingMessageType = (typeof SIGNALING_MESSAGE_TYPES)[number];
/** Ceiling applied to the raw UTF-8 byte length of an inbound message. */
export declare const DEFAULT_MAX_SIGNALING_MESSAGE_BYTES: number;
/** Ceiling applied to a single SDP body. */
export declare const DEFAULT_MAX_SDP_BYTES: number;
/** Ceiling applied to a serialized ICE candidate. */
export declare const DEFAULT_MAX_CANDIDATE_BYTES: number;
/** Ceiling for opaque identifiers supplied by peers. */
export declare const MAX_IDENTIFIER_LENGTH = 128;
export declare const MAX_SESSION_ID_LENGTH = 128;
export declare const MAX_DESKTOP_ID_LENGTH = 128;
export declare const MAX_CONNECTION_ID_LENGTH = 128;
export declare const HelloMessageSchema: z.ZodObject<{
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"hello">;
    role: z.ZodEnum<{
        desktop: "desktop";
        mobile: "mobile";
    }>;
    connectionId: z.ZodString;
}, z.core.$strict>;
export declare const DesktopPresenceMessageSchema: z.ZodObject<{
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"desktop-presence">;
    online: z.ZodBoolean;
    desktopId: z.ZodString;
}, z.core.$strict>;
export declare const OfferMessageSchema: z.ZodObject<{
    sdp: z.ZodString;
    sessionId: z.ZodString;
    targetRole: z.ZodEnum<{
        desktop: "desktop";
        mobile: "mobile";
    }>;
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"offer">;
}, z.core.$strict>;
export declare const AnswerMessageSchema: z.ZodObject<{
    sdp: z.ZodString;
    sessionId: z.ZodString;
    targetRole: z.ZodEnum<{
        desktop: "desktop";
        mobile: "mobile";
    }>;
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"answer">;
}, z.core.$strict>;
export declare const IceCandidateMessageSchema: z.ZodObject<{
    candidate: z.ZodRecord<z.ZodString, z.ZodUnknown>;
    sessionId: z.ZodString;
    targetRole: z.ZodEnum<{
        desktop: "desktop";
        mobile: "mobile";
    }>;
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"ice-candidate">;
}, z.core.$strict>;
export declare const HangupMessageSchema: z.ZodObject<{
    reason: z.ZodString;
    sessionId: z.ZodString;
    targetRole: z.ZodEnum<{
        desktop: "desktop";
        mobile: "mobile";
    }>;
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"hangup">;
}, z.core.$strict>;
export declare const ErrorMessageSchema: z.ZodObject<{
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"error">;
    code: z.ZodString;
    message: z.ZodString;
    sessionId: z.ZodOptional<z.ZodString>;
}, z.core.$strict>;
export declare const SignalingMessageSchema: z.ZodDiscriminatedUnion<[z.ZodObject<{
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"hello">;
    role: z.ZodEnum<{
        desktop: "desktop";
        mobile: "mobile";
    }>;
    connectionId: z.ZodString;
}, z.core.$strict>, z.ZodObject<{
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"desktop-presence">;
    online: z.ZodBoolean;
    desktopId: z.ZodString;
}, z.core.$strict>, z.ZodObject<{
    sdp: z.ZodString;
    sessionId: z.ZodString;
    targetRole: z.ZodEnum<{
        desktop: "desktop";
        mobile: "mobile";
    }>;
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"offer">;
}, z.core.$strict>, z.ZodObject<{
    sdp: z.ZodString;
    sessionId: z.ZodString;
    targetRole: z.ZodEnum<{
        desktop: "desktop";
        mobile: "mobile";
    }>;
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"answer">;
}, z.core.$strict>, z.ZodObject<{
    candidate: z.ZodRecord<z.ZodString, z.ZodUnknown>;
    sessionId: z.ZodString;
    targetRole: z.ZodEnum<{
        desktop: "desktop";
        mobile: "mobile";
    }>;
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"ice-candidate">;
}, z.core.$strict>, z.ZodObject<{
    reason: z.ZodString;
    sessionId: z.ZodString;
    targetRole: z.ZodEnum<{
        desktop: "desktop";
        mobile: "mobile";
    }>;
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"hangup">;
}, z.core.$strict>, z.ZodObject<{
    v: z.ZodLiteral<1>;
    type: z.ZodLiteral<"error">;
    code: z.ZodString;
    message: z.ZodString;
    sessionId: z.ZodOptional<z.ZodString>;
}, z.core.$strict>], "type">;
export type SignalingMessage = z.infer<typeof SignalingMessageSchema>;
export type HelloMessage = z.infer<typeof HelloMessageSchema>;
export type DesktopPresenceMessage = z.infer<typeof DesktopPresenceMessageSchema>;
export type OfferMessage = z.infer<typeof OfferMessageSchema>;
export type AnswerMessage = z.infer<typeof AnswerMessageSchema>;
export type IceCandidateMessage = z.infer<typeof IceCandidateMessageSchema>;
export type HangupMessage = z.infer<typeof HangupMessageSchema>;
export type ErrorMessage = z.infer<typeof ErrorMessageSchema>;
/** Messages that are only valid once bound to a signaling session. */
export declare const SESSION_SCOPED_MESSAGE_TYPES: readonly ["offer", "answer", "ice-candidate", "hangup"];
export type SessionScopedMessageType = (typeof SESSION_SCOPED_MESSAGE_TYPES)[number];
export type SessionScopedMessage = Extract<SignalingMessage, {
    type: SessionScopedMessageType;
}>;
export declare function isSessionScopedMessage(message: SignalingMessage): message is SessionScopedMessage;
/** Application-level rejection codes exchanged over the signaling socket. */
export declare const SignalingErrorCode: {
    readonly UnsupportedVersion: "UNSUPPORTED_VERSION";
    readonly UnknownMessageType: "UNKNOWN_MESSAGE_TYPE";
    readonly InvalidMessage: "INVALID_MESSAGE";
    readonly MessageTooLarge: "MESSAGE_TOO_LARGE";
    readonly RateLimited: "RATE_LIMITED";
    readonly NotAuthenticated: "NOT_AUTHENTICATED";
    readonly WrongRole: "WRONG_ROLE";
    readonly DesktopMismatch: "DESKTOP_MISMATCH";
    readonly UnknownSession: "UNKNOWN_SESSION";
    readonly SessionTakenOver: "SESSION_TAKEN_OVER";
    readonly PeerOffline: "PEER_OFFLINE";
    readonly InternalError: "INTERNAL_ERROR";
};
export type SignalingErrorCode = (typeof SignalingErrorCode)[keyof typeof SignalingErrorCode];
export type SignalingParseErrorCode = "MESSAGE_TOO_LARGE" | "INVALID_JSON" | "UNSUPPORTED_VERSION" | "UNKNOWN_MESSAGE_TYPE" | "INVALID_MESSAGE";
export interface SignalingParseError {
    code: SignalingParseErrorCode;
    message: string;
    sessionId?: string;
}
export type SignalingParseResult = {
    ok: true;
    message: SignalingMessage;
    bytes: number;
} | {
    ok: false;
    error: SignalingParseError;
    bytes: number;
};
export interface ParseSignalingOptions {
    /** Raw UTF-8 byte ceiling for the whole message. */
    maxBytes?: number;
    /** Raw UTF-8 byte ceiling for an SDP body. */
    maxSdpBytes?: number;
    /** Raw UTF-8 byte ceiling for a serialized ICE candidate. */
    maxCandidateBytes?: number;
}
export declare function utf8ByteLength(value: string): number;
/**
 * Parse and validate an inbound signaling frame.
 *
 * Size is enforced on the raw bytes *before* JSON.parse so a hostile peer
 * cannot force a large allocation by sending an oversized frame.
 */
export declare function parseSignalingMessage(raw: string | Buffer, options?: ParseSignalingOptions): SignalingParseResult;
/** Serialize a server-originated message. Callers must never log the result. */
export declare function serializeSignalingMessage(message: SignalingMessage): string;
export declare function signalingErrorMessage(code: string, message: string, sessionId?: string): ErrorMessage;
