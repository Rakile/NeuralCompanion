import { z } from "zod";
/**
 * HTTP contract for the NC Relay API.
 *
 * Everything in this file is shared by the server and by the NC desktop addon
 * and NC Remote mobile clients so that a single source of truth defines the
 * account, desktop, and ICE-server endpoints.
 */
export declare const HTTP_API_VERSION: "v1";
export declare const HTTP_API_PREFIX: "/v1";
export declare const USERNAME_MIN_LENGTH = 3;
export declare const USERNAME_MAX_LENGTH = 32;
export declare const PASSWORD_MIN_LENGTH = 12;
export declare const PASSWORD_MAX_LENGTH = 256;
export declare const EMAIL_MAX_LENGTH = 254;
export declare const DEVICE_LABEL_MAX_LENGTH = 64;
export declare const PUBLIC_IDENTITY_KEY_MAX_LENGTH = 512;
/** Usernames are compared case-insensitively after Unicode NFKC normalization. */
export declare const UsernameSchema: z.ZodString;
export declare const EmailSchema: z.ZodString;
export declare const PasswordSchema: z.ZodString;
export declare const DesktopIdSchema: z.ZodString;
export declare const DeviceLabelSchema: z.ZodString;
export declare const PublicIdentityKeySchema: z.ZodString;
export declare const RegisterRequestSchema: z.ZodObject<{
    username: z.ZodString;
    email: z.ZodString;
    password: z.ZodString;
    inviteCode: z.ZodString;
}, z.core.$strict>;
export declare const LoginRequestSchema: z.ZodObject<{
    identifier: z.ZodString;
    password: z.ZodString;
    role: z.ZodOptional<z.ZodEnum<{
        desktop: "desktop";
        mobile: "mobile";
    }>>;
    deviceLabel: z.ZodOptional<z.ZodString>;
}, z.core.$strict>;
export declare const RefreshRequestSchema: z.ZodObject<{
    refreshToken: z.ZodString;
}, z.core.$strict>;
export declare const LogoutRequestSchema: z.ZodObject<{
    refreshToken: z.ZodString;
    allSessions: z.ZodOptional<z.ZodBoolean>;
}, z.core.$strict>;
export declare const VerifyEmailRequestSchema: z.ZodObject<{
    token: z.ZodString;
}, z.core.$strict>;
export declare const ForgotPasswordRequestSchema: z.ZodObject<{
    email: z.ZodString;
}, z.core.$strict>;
export declare const ResetPasswordRequestSchema: z.ZodObject<{
    token: z.ZodString;
    password: z.ZodString;
}, z.core.$strict>;
export declare const DesktopRegisterRequestSchema: z.ZodObject<{
    desktopId: z.ZodString;
    publicIdentityKey: z.ZodString;
    deviceLabel: z.ZodOptional<z.ZodString>;
}, z.core.$strict>;
export declare const DesktopReplaceRequestSchema: z.ZodObject<{
    desktopId: z.ZodString;
    publicIdentityKey: z.ZodString;
    deviceLabel: z.ZodOptional<z.ZodString>;
    password: z.ZodString;
}, z.core.$strict>;
export declare const AccountSchema: z.ZodObject<{
    id: z.ZodString;
    username: z.ZodString;
    email: z.ZodString;
    emailVerified: z.ZodBoolean;
    createdAt: z.ZodString;
}, z.core.$strip>;
export declare const TokenPairSchema: z.ZodObject<{
    accessToken: z.ZodString;
    refreshToken: z.ZodString;
    tokenType: z.ZodLiteral<"Bearer">;
    expiresIn: z.ZodNumber;
    refreshExpiresIn: z.ZodNumber;
}, z.core.$strip>;
export declare const AuthResponseSchema: z.ZodObject<{
    account: z.ZodObject<{
        id: z.ZodString;
        username: z.ZodString;
        email: z.ZodString;
        emailVerified: z.ZodBoolean;
        createdAt: z.ZodString;
    }, z.core.$strip>;
    accessToken: z.ZodString;
    refreshToken: z.ZodString;
    tokenType: z.ZodLiteral<"Bearer">;
    expiresIn: z.ZodNumber;
    refreshExpiresIn: z.ZodNumber;
}, z.core.$strip>;
export declare const MfaPendingResponseSchema: z.ZodUnion<readonly [z.ZodObject<{
    status: z.ZodLiteral<"mfa_required">;
    challengeToken: z.ZodString;
    expiresIn: z.ZodNumber;
}, z.core.$strict>, z.ZodObject<{
    status: z.ZodLiteral<"mfa_enrollment_required">;
    enrollmentToken: z.ZodString;
    expiresIn: z.ZodNumber;
}, z.core.$strict>]>;
export declare const LoginResponseSchema: z.ZodUnion<readonly [z.ZodObject<{
    account: z.ZodObject<{
        id: z.ZodString;
        username: z.ZodString;
        email: z.ZodString;
        emailVerified: z.ZodBoolean;
        createdAt: z.ZodString;
    }, z.core.$strip>;
    accessToken: z.ZodString;
    refreshToken: z.ZodString;
    tokenType: z.ZodLiteral<"Bearer">;
    expiresIn: z.ZodNumber;
    refreshExpiresIn: z.ZodNumber;
}, z.core.$strict>, z.ZodUnion<readonly [z.ZodObject<{
    status: z.ZodLiteral<"mfa_required">;
    challengeToken: z.ZodString;
    expiresIn: z.ZodNumber;
}, z.core.$strict>, z.ZodObject<{
    status: z.ZodLiteral<"mfa_enrollment_required">;
    enrollmentToken: z.ZodString;
    expiresIn: z.ZodNumber;
}, z.core.$strict>]>]>;
export declare const MfaEnrollRequestSchema: z.ZodObject<{
    enrollmentToken: z.ZodString;
}, z.core.$strict>;
export declare const MfaConfirmRequestSchema: z.ZodObject<{
    enrollmentToken: z.ZodString;
    code: z.ZodString;
}, z.core.$strict>;
export declare const MfaVerifyRequestSchema: z.ZodObject<{
    challengeToken: z.ZodString;
    code: z.ZodOptional<z.ZodString>;
    recoveryCode: z.ZodOptional<z.ZodString>;
}, z.core.$strict>;
export declare const MfaEnrollmentResponseSchema: z.ZodObject<{
    secret: z.ZodString;
    otpauthUri: z.ZodString;
}, z.core.$strict>;
export declare const MfaConfirmResponseSchema: z.ZodObject<{
    account: z.ZodObject<{
        id: z.ZodString;
        username: z.ZodString;
        email: z.ZodString;
        emailVerified: z.ZodBoolean;
        createdAt: z.ZodString;
    }, z.core.$strip>;
    accessToken: z.ZodString;
    refreshToken: z.ZodString;
    tokenType: z.ZodLiteral<"Bearer">;
    expiresIn: z.ZodNumber;
    refreshExpiresIn: z.ZodNumber;
    recoveryCodes: z.ZodArray<z.ZodString>;
}, z.core.$strip>;
export type MfaPendingResponse = z.infer<typeof MfaPendingResponseSchema>;
export type LoginResponse = z.infer<typeof LoginResponseSchema>;
export declare const DesktopRegistrationSchema: z.ZodObject<{
    userId: z.ZodString;
    desktopId: z.ZodString;
    publicIdentityKey: z.ZodString;
    deviceLabel: z.ZodNullable<z.ZodString>;
    createdAt: z.ZodString;
    lastSeenAt: z.ZodNullable<z.ZodString>;
}, z.core.$strip>;
export declare const IceServerSchema: z.ZodObject<{
    urls: z.ZodArray<z.ZodString>;
    username: z.ZodOptional<z.ZodString>;
    credential: z.ZodOptional<z.ZodString>;
}, z.core.$strip>;
export declare const IceServersResponseSchema: z.ZodObject<{
    iceServers: z.ZodArray<z.ZodObject<{
        urls: z.ZodArray<z.ZodString>;
        username: z.ZodOptional<z.ZodString>;
        credential: z.ZodOptional<z.ZodString>;
    }, z.core.$strip>>;
    ttlSeconds: z.ZodNumber;
    expiresAt: z.ZodString;
    protocolVersion: z.ZodLiteral<1>;
}, z.core.$strip>;
export declare const ErrorResponseSchema: z.ZodObject<{
    error: z.ZodObject<{
        code: z.ZodString;
        message: z.ZodString;
        requestId: z.ZodOptional<z.ZodString>;
    }, z.core.$strip>;
}, z.core.$strip>;
export declare const HealthResponseSchema: z.ZodObject<{
    status: z.ZodEnum<{
        ok: "ok";
        degraded: "degraded";
        unavailable: "unavailable";
    }>;
}, z.core.$strip>;
export type RegisterRequest = z.infer<typeof RegisterRequestSchema>;
export type LoginRequest = z.infer<typeof LoginRequestSchema>;
export type RefreshRequest = z.infer<typeof RefreshRequestSchema>;
export type LogoutRequest = z.infer<typeof LogoutRequestSchema>;
export type VerifyEmailRequest = z.infer<typeof VerifyEmailRequestSchema>;
export type ForgotPasswordRequest = z.infer<typeof ForgotPasswordRequestSchema>;
export type ResetPasswordRequest = z.infer<typeof ResetPasswordRequestSchema>;
export type DesktopRegisterRequest = z.infer<typeof DesktopRegisterRequestSchema>;
export type DesktopReplaceRequest = z.infer<typeof DesktopReplaceRequestSchema>;
export type Account = z.infer<typeof AccountSchema>;
export type TokenPair = z.infer<typeof TokenPairSchema>;
export type AuthResponse = z.infer<typeof AuthResponseSchema>;
export type DesktopRegistration = z.infer<typeof DesktopRegistrationSchema>;
export type IceServer = z.infer<typeof IceServerSchema>;
export type IceServersResponse = z.infer<typeof IceServersResponseSchema>;
export type ErrorResponse = z.infer<typeof ErrorResponseSchema>;
export type HealthResponse = z.infer<typeof HealthResponseSchema>;
/** Stable public error codes. Unknown accounts and bad passwords share one code. */
export declare const ApiErrorCode: {
    readonly MfaInvalid: "MFA_INVALID";
    readonly InviteInvalid: "INVITE_INVALID";
    readonly ValidationFailed: "VALIDATION_FAILED";
    readonly InvalidCredentials: "INVALID_CREDENTIALS";
    readonly UsernameTaken: "USERNAME_TAKEN";
    readonly EmailTaken: "EMAIL_TAKEN";
    readonly EmailNotVerified: "EMAIL_NOT_VERIFIED";
    readonly InvalidToken: "INVALID_TOKEN";
    readonly InvalidResetToken: "INVALID_RESET_TOKEN";
    readonly TokenExpired: "TOKEN_EXPIRED";
    readonly TokenReused: "TOKEN_REUSED";
    readonly Unauthorized: "UNAUTHORIZED";
    readonly Forbidden: "FORBIDDEN";
    readonly NotFound: "NOT_FOUND";
    readonly DesktopReplacementRequired: "DESKTOP_REPLACEMENT_REQUIRED";
    readonly DesktopNotFound: "DESKTOP_NOT_FOUND";
    readonly DesktopAlreadyRegistered: "DESKTOP_ALREADY_REGISTERED";
    readonly RateLimited: "RATE_LIMITED";
    readonly PayloadTooLarge: "PAYLOAD_TOO_LARGE";
    readonly ServiceUnavailable: "SERVICE_UNAVAILABLE";
    readonly InternalError: "INTERNAL_ERROR";
};
export type ApiErrorCode = (typeof ApiErrorCode)[keyof typeof ApiErrorCode];
export declare const HTTP_STATUS_BY_ERROR_CODE: Record<string, number>;
