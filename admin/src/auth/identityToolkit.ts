/**
 * Firebase Authentication over REST (Identity Toolkit), as the mobile app does (ADR-0028):
 * email and password, then a TOTP second factor. Staff accounts must use the second factor;
 * the API refuses admin calls without it (ADM-007).
 *
 * TOTP needs Firebase Authentication with Identity Platform and the TOTP provider turned on
 * for the project (docs/11 §1.15).
 */

const BASE = 'https://identitytoolkit.googleapis.com';

export class IdentityError extends Error {
  /** Firebase's error code (`INVALID_LOGIN_CREDENTIALS`, `INVALID_MFA_PENDING_CREDENTIAL`, ...). */
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.name = 'IdentityError';
    this.code = code;
  }
}

async function call<T>(path: string, apiKey: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}?key=${encodeURIComponent(apiKey)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      credentials: 'omit',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
    });
  } catch {
    throw new IdentityError('NETWORK_ERROR');
  }
  const json = (await response.json().catch(() => ({}))) as {
    error?: { message?: string };
  } & T;
  if (!response.ok) {
    // Messages look like "INVALID_LOGIN_CREDENTIALS" or "TOO_MANY_ATTEMPTS_TRY_LATER : ...".
    const message = json.error?.message ?? 'UNKNOWN';
    throw new IdentityError(message.split(/[ :]/)[0] || 'UNKNOWN');
  }
  return json;
}

export type PasswordResult =
  | { kind: 'signed_in'; idToken: string }
  | { kind: 'second_factor'; pendingCredential: string; enrollmentId: string };

interface SignInResponse {
  idToken?: string;
  mfaPendingCredential?: string;
  mfaInfo?: { mfaEnrollmentId: string; totpInfo?: object; phoneInfo?: string }[];
}

export async function signInWithPassword(
  apiKey: string,
  email: string,
  password: string,
): Promise<PasswordResult> {
  const result = await call<SignInResponse>('/v1/accounts:signInWithPassword', apiKey, {
    email,
    password,
    returnSecureToken: true,
  });
  if (result.mfaPendingCredential) {
    const totp = result.mfaInfo?.find((factor) => factor.totpInfo !== undefined);
    if (!totp) throw new IdentityError('TOTP_NOT_ENROLLED');
    return {
      kind: 'second_factor',
      pendingCredential: result.mfaPendingCredential,
      enrollmentId: totp.mfaEnrollmentId,
    };
  }
  if (!result.idToken) throw new IdentityError('UNKNOWN');
  return { kind: 'signed_in', idToken: result.idToken };
}

export async function finishSecondFactor(
  apiKey: string,
  pendingCredential: string,
  enrollmentId: string,
  code: string,
): Promise<string> {
  const result = await call<{ idToken: string }>('/v2/accounts/mfaSignIn:finalize', apiKey, {
    mfaPendingCredential: pendingCredential,
    mfaEnrollmentId: enrollmentId,
    totpVerificationInfo: { verificationCode: code },
  });
  return result.idToken;
}

export interface TotpEnrollment {
  sharedSecretKey: string;
  sessionInfo: string;
  verificationCodeLength: number;
  periodSec: number;
  hashingAlgorithm: string;
}

export async function startTotpEnrollment(apiKey: string, idToken: string): Promise<TotpEnrollment> {
  const result = await call<{ totpSessionInfo: TotpEnrollment }>(
    '/v2/accounts/mfaEnrollment:start',
    apiKey,
    { idToken, totpEnrollmentInfo: {} },
  );
  return result.totpSessionInfo;
}

export async function finishTotpEnrollment(
  apiKey: string,
  idToken: string,
  sessionInfo: string,
  code: string,
): Promise<void> {
  await call('/v2/accounts/mfaEnrollment:finalize', apiKey, {
    idToken,
    displayName: 'Authenticator app',
    totpVerificationInfo: { sessionInfo, verificationCode: code },
  });
}

/** The `otpauth://` URI an authenticator app reads from the QR code. */
export function otpauthUri(email: string, enrollment: TotpEnrollment): string {
  const issuer = 'Travel Buddy Staff';
  const label = encodeURIComponent(`${issuer}:${email}`);
  const params = new URLSearchParams({
    secret: enrollment.sharedSecretKey,
    issuer,
    algorithm: (enrollment.hashingAlgorithm || 'SHA1').replace('HMAC_', '').replace('-', ''),
    digits: String(enrollment.verificationCodeLength || 6),
    period: String(enrollment.periodSec || 30),
  });
  return `otpauth://totp/${label}?${params.toString()}`;
}
