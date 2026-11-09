import { NextResponse, type NextRequest } from 'next/server';
import { isApiError } from '@travelbuddy/api-client';
import { readSession, verifyCsrf } from '@/server/auth';
import { env } from '@/server/env';
import { serverApi } from '@/server/platform';

export const dynamic = 'force-dynamic';

/** ADR-0013: mints a single-use realtime ticket for the browser's WebSocket `auth` frame. */
export async function POST(request: NextRequest) {
  if (!verifyCsrf(request)) return NextResponse.json({ code: 'csrf_failed', status: 403 }, { status: 403 });
  const session = await readSession(request);
  if (!session) return NextResponse.json({ code: 'unauthenticated', status: 401 }, { status: 401 });
  try {
    const api = await serverApi({ accessToken: session.at });
    const ticket = await api.realtime.ticket();
    return NextResponse.json({ ...ticket, url: env().realtimeUrl }, { headers: { 'cache-control': 'no-store' } });
  } catch (error) {
    if (isApiError(error)) return NextResponse.json(error.problem, { status: error.status || 502 });
    throw error;
  }
}
