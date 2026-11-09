import { NextResponse, type NextRequest } from 'next/server';
import type { ApiRequest, HttpMethod, QueryValue } from '@travelbuddy/api-client';
import { clearSessionCookies, readSession, refreshSession, requestIdFrom, verifyCsrf, writeSessionCookie } from '@/server/auth';
import { platformTransport } from '@/server/platform';
import { needsRefresh, type SessionData } from '@/server/session';

/**
 * BFF proxy: browser → `/api/v1/*` (cookie + CSRF) → platform `/v1/*` (Bearer).
 * ADR-0011. Responses are always `private, no-store`.
 */
export const dynamic = 'force-dynamic';

/** Never proxied: token-bearing auth endpoints, dev IdP, provider webhooks, realtime tickets. */
const BLOCKED = [/^auth(\/|$)/, /^dev(\/|$)/, /^billing\/webhooks(\/|$)/, /^realtime(\/|$)/, /^internal(\/|$)/];
const FORWARD_RESPONSE_HEADERS = [
  'content-type',
  'etag',
  'retry-after',
  'ratelimit-limit',
  'ratelimit-remaining',
  'ratelimit-reset',
  'x-request-id',
  'x-tb-mock',
  'idempotent-replayed',
];
const MAX_BODY_BYTES = 1_000_000;

function problem(status: number, code: string, title: string, requestId: string) {
  return NextResponse.json(
    { type: `https://errors.travelbuddy.app/${code}`, title, status, code, request_id: requestId },
    { status, headers: { 'content-type': 'application/problem+json', 'cache-control': 'private, no-store', 'x-request-id': requestId } },
  );
}

function queryFrom(params: URLSearchParams): Record<string, QueryValue> {
  const out: Record<string, QueryValue> = {};
  for (const key of new Set(params.keys())) {
    const all = params.getAll(key);
    out[key] = all.length > 1 ? all : (all[0] ?? '');
  }
  return out;
}

async function handle(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const requestId = requestIdFrom(request);
  const method = request.method.toUpperCase() as HttpMethod;
  const { path: segments } = await context.params;
  const subpath = segments.map(encodeURIComponent).join('/');

  if (BLOCKED.some((re) => re.test(segments.join('/')))) return problem(404, 'not_found', 'Not found', requestId);
  if (method !== 'GET' && !verifyCsrf(request)) return problem(403, 'csrf_failed', 'CSRF check failed', requestId);

  let body: unknown;
  if (method !== 'GET' && method !== 'DELETE') {
    const text = await request.text();
    if (text.length > MAX_BODY_BYTES) return problem(413, 'payload_too_large', 'Payload too large', requestId);
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        return problem(400, 'validation_failed', 'Body must be JSON', requestId);
      }
    }
  }

  // ADM-009: admin mutations carry a human justification; validate its shape before forwarding.
  const justification = request.headers.get('x-audit-justification')?.trim() ?? null;
  if (justification !== null && (justification.length < 10 || justification.length > 500)) {
    return problem(400, 'justification_required', 'X-Audit-Justification must be 10–500 characters', requestId);
  }

  let session: SessionData | null = await readSession(request);
  let refreshed = false;
  let signedOut = false;

  const tryRefresh = async () => {
    if (!session) return;
    const next = await refreshSession(session, requestId);
    if (next) {
      session = next;
      refreshed = true;
    } else {
      session = null;
      signedOut = true;
    }
  };

  if (session && needsRefresh(session, Date.now(), 15_000)) await tryRefresh();

  const transport = await platformTransport();
  const build = (): ApiRequest => ({
    method,
    path: `/v1/${subpath}`,
    query: queryFrom(request.nextUrl.searchParams),
    body,
    idempotencyKey: request.headers.get('idempotency-key') ?? undefined,
    headers: {
      'Accept-Language': request.headers.get('accept-language') ?? 'en',
      'X-Request-ID': requestId,
      ...(request.headers.get('user-agent') ? { 'User-Agent': (request.headers.get('user-agent') as string).slice(0, 512) } : {}),
      ...(request.headers.get('if-match') ? { 'If-Match': request.headers.get('if-match') as string } : {}),
      ...(justification ? { 'X-Audit-Justification': justification } : {}),
      ...(session ? { Authorization: `Bearer ${session.at}` } : {}),
    },
  });

  let upstream = await transport.send(build());
  const upstreamCode = (upstream.body as { code?: string } | undefined)?.code;
  if (upstream.status === 401 && upstreamCode === 'token_expired' && session && !refreshed) {
    await tryRefresh();
    if (session) upstream = await transport.send(build());
  }

  const response =
    upstream.body === undefined
      ? new NextResponse(null, { status: upstream.status })
      : NextResponse.json(upstream.body, { status: upstream.status });
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers[name];
    if (value) response.headers.set(name, value);
  }
  response.headers.set('cache-control', 'private, no-store');
  response.headers.set('x-request-id', upstream.headers['x-request-id'] ?? requestId);

  if (refreshed && session) await writeSessionCookie(response, session);
  if (signedOut) clearSessionCookies(response);
  return response;
}

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE };
