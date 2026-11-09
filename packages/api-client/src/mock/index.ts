/**
 * MOCK ADAPTER — server-side development/test simulation of the Travel Buddy `/v1` platform API.
 *
 * Policy (docs/web/01 §7.1):
 *  - enabled only when TB_API_MODE=mock and APP_ENV ∈ {development, test} (enforced by the app);
 *  - never imported by browser code;
 *  - every response carries `X-TB-Mock: 1`;
 *  - payments, AI, media, chat, discovery, groups, trips and admin analytics are NOT simulated:
 *    they return 503 `feature_not_available_in_mock`.
 */
import { SUPPORTED_LOCALES, type LocaleCode } from '@travelbuddy/domain-types';
import type { ApiRequest, RawResponse, Transport } from '../core/types';
import { MockDb } from './db';
import { buildRouter, rebuildFromClaims, type MockContext } from './handlers';
import { verifyMockToken } from './tokens';
import { uuidv7 } from './ids';
import { MockHttpError, problem, unauthenticated } from './problems';
import { PERSONAS } from './fixtures/social';

export interface MockPlatformOptions {
  now?: () => number;
  /** HMAC key for mock tokens; pass the web's SESSION_SECRET so demo instances agree. */
  tokenSecret?: string;
}

export interface MockPlatform {
  db: MockDb;
  transport: Transport;
}

/** Idempotency-Key is required on these resource-creating POSTs (doc 02 §5). */
const IDEMPOTENT_POSTS = [/^\/v1\/posts$/, /^\/v1\/posts\/[^/]+\/comments$/, /^\/v1\/reports$/, /^\/v1\/auth\/register$/];

function resolveLocale(acceptLanguage: string | undefined): LocaleCode {
  const tags = (acceptLanguage ?? '')
    .split(',')
    .map((part) => part.split(';')[0]?.trim().toLowerCase() ?? '')
    .filter(Boolean);
  for (const tag of tags) {
    const exact = SUPPORTED_LOCALES.find((l) => l.toLowerCase() === tag);
    if (exact) return exact;
    const base = tag.split('-')[0];
    const partial = SUPPORTED_LOCALES.find((l) => l.toLowerCase().split('-')[0] === base);
    if (partial) return partial;
  }
  return 'en';
}

function lowerKeys(headers: Record<string, string> | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(headers ?? {})) out[k.toLowerCase()] = v;
  return out;
}

export function createMockPlatform(options: MockPlatformOptions = {}): MockPlatform {
  const now = options.now ?? Date.now;
  const db = options.tokenSecret ? new MockDb(now, options.tokenSecret) : new MockDb(now);
  const router = buildRouter();

  const respond = (status: number, body: unknown, requestId: string, extra: Record<string, string> = {}): RawResponse => ({
    status,
    body,
    headers: {
      ...(body === undefined
        ? {}
        : { 'content-type': status >= 400 ? 'application/problem+json' : 'application/json' }),
      'x-tb-mock': '1',
      'x-request-id': requestId,
      ...extra,
    },
  });

  const transport: Transport = {
    async send(request: ApiRequest): Promise<RawResponse> {
      const headers = lowerKeys(request.headers);
      const requestId = headers['x-request-id'] ?? uuidv7(now());
      const path = request.path.split('?')[0] ?? request.path;
      const match = router.match(request.method, path);
      if (!match) {
        return respond(404, { ...problem(404, 'not_found', `No mock route for ${request.method} ${path}`).problem, request_id: requestId }, requestId);
      }

      const authorization = headers.authorization ?? '';
      const idempotencyKey = request.idempotencyKey ?? headers['idempotency-key'];
      const needsKey = request.method === 'POST' && IDEMPOTENT_POSTS.some((re) => re.test(path));
      const fingerprint = `${request.method} ${path} ${JSON.stringify(request.body ?? null)}`;
      const idemKey = idempotencyKey ? `${authorization}|${idempotencyKey}` : null;

      try {
        if (needsKey && !idempotencyKey) {
          throw problem(400, 'validation_failed', 'Idempotency-Key header is required.', [
            { field: 'Idempotency-Key', code: 'required', message: 'Idempotency-Key header is required.' },
          ]);
        }
        if (idemKey) {
          const previous = db.idempotency.get(idemKey);
          if (previous) {
            if (previous.fingerprint !== fingerprint) {
              throw problem(409, 'idempotency_key_reused', 'This Idempotency-Key was used for a different request.');
            }
            return respond(previous.status, previous.body, requestId, { 'idempotent-replayed': 'true' });
          }
        }

        const query = request.query ?? {};
        const resolveAuth = () => {
          const token = /^Bearer (.+)$/.exec(authorization)?.[1];
          // Signed, self-describing tokens: any instance can validate them (serverless demos).
          const claims = verifyMockToken(token, db.tokenSecret);
          if (!token || !claims || claims.k !== 'a') throw unauthenticated();
          if (claims.e < now()) throw problem(401, 'token_expired', 'The access token has expired.');
          const known = db.sessions.get(claims.s);
          const rebuilt = known ? { session: known, user: db.users.get(known.userId) } : rebuildFromClaims(db, claims, token, now());
          const session = rebuilt?.session;
          const user = rebuilt?.user;
          if (!session || session.revoked || !user) throw problem(401, 'session_revoked', 'The session is no longer valid.');
          if (user.status === 'suspended') throw problem(403, 'account_suspended', 'This account is suspended.');
          session.lastSeenAt = now();
          return { user, session };
        };
        const ctx: MockContext = {
          db,
          method: request.method,
          params: match.params,
          query: (name) => {
            const v = query[name];
            if (v === undefined || v === null) return undefined;
            return Array.isArray(v) ? (v[0] === undefined ? undefined : String(v[0])) : String(v);
          },
          body: typeof request.body === 'object' && request.body !== null ? (request.body as Record<string, unknown>) : {},
          headers,
          locale: resolveLocale(headers['accept-language']),
          now: now(),
          auth: resolveAuth,
          optionalAuth: () => (authorization ? resolveAuth() : null),
        };
        const result = match.handler(ctx);
        if (idemKey && result.status < 500) {
          db.idempotency.set(idemKey, { fingerprint, status: result.status, body: result.body });
        }
        return respond(result.status, result.body, requestId);
      } catch (error) {
        if (error instanceof MockHttpError) {
          return respond(error.problem.status, { type: 'about:blank', ...error.problem, request_id: requestId }, requestId, error.headers);
        }
        throw error;
      }
    },
  };

  return { db, transport };
}

const GLOBAL_KEY = Symbol.for('travelbuddy.mockPlatform');

/**
 * Process-wide singleton so that every server entry point (RSC, route handlers, proxy) and every
 * dev-server hot reload sees the same in-memory state.
 */
export function getSharedMockPlatform(options: MockPlatformOptions = {}): MockPlatform {
  const g = globalThis as unknown as Record<symbol, MockPlatform | undefined>;
  return (g[GLOBAL_KEY] ??= createMockPlatform(options));
}

export interface DevPersona {
  sub: string;
  handle: string;
  display_name: string;
  email: string;
  note: string;
  /** Holds a staff role, so dev sign-in simulates a second factor (ADM-007 requires MFA for staff). */
  staff: boolean;
}

/** Personas offered by the development persona picker (`/dev/login`). */
export function listDevPersonas(): DevPersona[] {
  return PERSONAS.map((p) => ({
    sub: `persona:${p.handle}`,
    handle: p.handle,
    display_name: p.display_name,
    email: p.email,
    note: p.persona_note,
    staff: (p.roles ?? []).length > 0,
  }));
}
