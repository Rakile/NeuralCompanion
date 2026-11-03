import { z } from "zod";
import { ClientRoleSchema, SIGNALING_PROTOCOL_VERSION } from "./signaling.js";

/**
 * HTTP contract for the NC Relay API.
 *
 * Everything in this file is shared by the server and by the NC desktop addon
 * and NC Remote mobile clients so that a single source of truth defines the
 * account, desktop, and ICE-server endpoints.
 */

export const HTTP_API_VERSION = "v1" as const;
export const HTTP_API_PREFIX = `/${HTTP_API_VERSION}` as const;

export const USERNAME_MIN_LENGTH = 3;
export const USERNAME_MAX_LENGTH = 32;
export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MAX_LENGTH = 256;
export const EMAIL_MAX_LENGTH = 254;
export const DEVICE_LABEL_MAX_LENGTH = 64;
export const PUBLIC_IDENTITY_KEY_MAX_LENGTH = 512;

/** Usernames are compared case-insensitively after Unicode NFKC normalization. */
export const UsernameSchema = z
  .string()
  .trim()
  .min(USERNAME_MIN_LENGTH)
  .max(USERNAME_MAX_LENGTH)
  .regex(
    /^[A-Za-z0-9][A-Za-z0-9_-]*$/,
    "username must start with a letter or digit and may contain only letters, digits, underscores, and hyphens",
  );

export const EmailSchema = z
  .string()
  .trim()
  .toLowerCase()
  .max(EMAIL_MAX_LENGTH)
  .email("a valid email address is required");

export const PasswordSchema = z
  .string()
  .min(PASSWORD_MIN_LENGTH, `password must be at least ${PASSWORD_MIN_LENGTH} characters`)
  .max(PASSWORD_MAX_LENGTH)
  .refine(
    (value) => value.normalize("NFKC").trim().length > 0,
    "password must not be empty or whitespace-only",
  );

export const DesktopIdSchema = z.string().uuid("desktopId must be a UUID");

export const DeviceLabelSchema = z.string().trim().min(1).max(DEVICE_LABEL_MAX_LENGTH);

export const PublicIdentityKeySchema = z
  .string()
  .min(1)
  .max(PUBLIC_IDENTITY_KEY_MAX_LENGTH);

export const RegisterRequestSchema = z
  .object({
    username: UsernameSchema,
    email: EmailSchema,
    password: PasswordSchema,
    inviteCode: z.string().min(20).max(128),
  })
  .strict();

export const LoginRequestSchema = z
  .object({
    /** Either the username or the email address. */
    identifier: z.string().trim().min(1).max(EMAIL_MAX_LENGTH),
    password: z.string().min(1).max(PASSWORD_MAX_LENGTH),
    /**
     * Which client is signing in. One credential works for both the NC desktop
     * addon and the NC Remote mobile app; the role is what makes the issued
     * tokens usable at the signaling gateway. Defaults to `mobile`.
     */
    role: ClientRoleSchema.optional(),
    deviceLabel: DeviceLabelSchema.optional(),
  })
  .strict();

export const RefreshRequestSchema = z
  .object({
    refreshToken: z.string().min(1).max(512),
  })
  .strict();

export const LogoutRequestSchema = z
  .object({
    refreshToken: z.string().min(1).max(512),
    /** Revoke every refresh token for the account, not only this one. */
    allSessions: z.boolean().optional(),
  })
  .strict();

export const VerifyEmailRequestSchema = z
  .object({
    token: z.string().min(1).max(512),
  })
  .strict();

export const ForgotPasswordRequestSchema = z
  .object({
    email: EmailSchema,
  })
  .strict();

export const ResetPasswordRequestSchema = z
  .object({
    token: z.string().min(1).max(512),
    password: PasswordSchema,
  })
  .strict();

export const DesktopRegisterRequestSchema = z
  .object({
    desktopId: DesktopIdSchema,
    publicIdentityKey: PublicIdentityKeySchema,
    deviceLabel: DeviceLabelSchema.optional(),
  })
  .strict();

export const DesktopReplaceRequestSchema = z
  .object({
    desktopId: DesktopIdSchema,
    publicIdentityKey: PublicIdentityKeySchema,
    deviceLabel: DeviceLabelSchema.optional(),
    /** Recent password confirmation is mandatory for replacement. */
    password: z.string().min(1).max(PASSWORD_MAX_LENGTH),
  })
  .strict();

export const AccountSchema = z.object({
  id: z.string().uuid(),
  username: z.string(),
  email: z.string().email(),
  emailVerified: z.boolean(),
  createdAt: z.string().datetime(),
});

export const TokenPairSchema = z.object({
  accessToken: z.string(),
  refreshToken: z.string(),
  tokenType: z.literal("Bearer"),
  /** Access-token lifetime in seconds. */
  expiresIn: z.number().int().positive(),
  /** Refresh-token lifetime in seconds. */
  refreshExpiresIn: z.number().int().positive(),
});

export const AuthResponseSchema = z.object({
  ...TokenPairSchema.shape,
  account: AccountSchema,
});

export const MfaPendingResponseSchema = z.union([
  z.object({status:z.literal("mfa_required"),challengeToken:z.string().min(20).max(128),expiresIn:z.number().int().positive().max(300)}).strict(),
  z.object({status:z.literal("mfa_enrollment_required"),enrollmentToken:z.string().min(20).max(128),expiresIn:z.number().int().positive().max(600)}).strict(),
]);
export const LoginResponseSchema = z.union([AuthResponseSchema.strict(), MfaPendingResponseSchema]);
export const MfaEnrollRequestSchema = z.object({enrollmentToken:z.string().min(20).max(128)}).strict();
export const MfaConfirmRequestSchema = MfaEnrollRequestSchema.extend({code:z.string().regex(/^\d{6}$/)}).strict();
export const MfaVerifyRequestSchema = z.object({challengeToken:z.string().min(20).max(128),code:z.string().regex(/^\d{6}$/).optional(),recoveryCode:z.string().regex(/^[a-fA-F0-9]{8}-[a-fA-F0-9]{8}$/).optional()}).strict().refine(v => (v.code !== undefined) !== (v.recoveryCode !== undefined));
export const MfaEnrollmentResponseSchema = z.object({secret:z.string().regex(/^[A-Z2-7]{32}$/),otpauthUri:z.string().startsWith("otpauth://totp/")}).strict();
export const MfaConfirmResponseSchema = AuthResponseSchema.extend({recoveryCodes:z.array(z.string()).length(10)});
export type MfaPendingResponse = z.infer<typeof MfaPendingResponseSchema>;
export type LoginResponse = z.infer<typeof LoginResponseSchema>;

export const DesktopRegistrationSchema = z.object({
  userId: z.string().uuid(),
  desktopId: z.string().uuid(),
  publicIdentityKey: z.string(),
  deviceLabel: z.string().nullable(),
  createdAt: z.string().datetime(),
  lastSeenAt: z.string().datetime().nullable(),
});

export const IceServerSchema = z.object({
  urls: z.array(z.string()).min(1),
  username: z.string().optional(),
  credential: z.string().optional(),
});

export const IceServersResponseSchema = z.object({
  iceServers: z.array(IceServerSchema).min(1),
  ttlSeconds: z.number().int().positive(),
  expiresAt: z.string().datetime(),
  protocolVersion: z.literal(SIGNALING_PROTOCOL_VERSION),
});

export const ErrorResponseSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    requestId: z.string().optional(),
  }),
});

export const HealthResponseSchema = z.object({
  status: z.enum(["ok", "degraded", "unavailable"]),
});

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
export const ApiErrorCode = {
  MfaInvalid: "MFA_INVALID",
  InviteInvalid: "INVITE_INVALID",
  ValidationFailed: "VALIDATION_FAILED",
  InvalidCredentials: "INVALID_CREDENTIALS",
  UsernameTaken: "USERNAME_TAKEN",
  EmailTaken: "EMAIL_TAKEN",
  EmailNotVerified: "EMAIL_NOT_VERIFIED",
  InvalidToken: "INVALID_TOKEN",
  InvalidResetToken: "INVALID_RESET_TOKEN",
  TokenExpired: "TOKEN_EXPIRED",
  TokenReused: "TOKEN_REUSED",
  Unauthorized: "UNAUTHORIZED",
  Forbidden: "FORBIDDEN",
  NotFound: "NOT_FOUND",
  DesktopReplacementRequired: "DESKTOP_REPLACEMENT_REQUIRED",
  DesktopNotFound: "DESKTOP_NOT_FOUND",
  DesktopAlreadyRegistered: "DESKTOP_ALREADY_REGISTERED",
  RateLimited: "RATE_LIMITED",
  PayloadTooLarge: "PAYLOAD_TOO_LARGE",
  ServiceUnavailable: "SERVICE_UNAVAILABLE",
  InternalError: "INTERNAL_ERROR",
} as const;
export type ApiErrorCode = (typeof ApiErrorCode)[keyof typeof ApiErrorCode];

export const HTTP_STATUS_BY_ERROR_CODE: Record<string, number> = {
  [ApiErrorCode.MfaInvalid]: 401,
  [ApiErrorCode.InviteInvalid]: 400,
  [ApiErrorCode.ValidationFailed]: 400,
  [ApiErrorCode.InvalidCredentials]: 401,
  [ApiErrorCode.EmailNotVerified]: 403,
  [ApiErrorCode.InvalidToken]: 401,
  [ApiErrorCode.InvalidResetToken]: 400,
  [ApiErrorCode.TokenExpired]: 401,
  [ApiErrorCode.TokenReused]: 401,
  [ApiErrorCode.Unauthorized]: 401,
  [ApiErrorCode.Forbidden]: 403,
  [ApiErrorCode.NotFound]: 404,
  [ApiErrorCode.DesktopReplacementRequired]: 409,
  [ApiErrorCode.DesktopNotFound]: 404,
  [ApiErrorCode.DesktopAlreadyRegistered]: 409,
  [ApiErrorCode.UsernameTaken]: 409,
  [ApiErrorCode.EmailTaken]: 409,
  [ApiErrorCode.RateLimited]: 429,
  [ApiErrorCode.PayloadTooLarge]: 413,
  [ApiErrorCode.ServiceUnavailable]: 503,
  [ApiErrorCode.InternalError]: 500,
};
