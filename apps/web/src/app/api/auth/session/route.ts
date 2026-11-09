import { NextResponse, type NextRequest } from 'next/server';
import { readSession } from '@/server/auth';

export const dynamic = 'force-dynamic';

/** Minimal session summary for client code. Never returns tokens. */
export async function GET(request: NextRequest) {
  const session = await readSession(request);
  return NextResponse.json(
    session ? { authenticated: true, user_id: session.uid, roles: session.roles } : { authenticated: false },
    { headers: { 'cache-control': 'private, no-store' } },
  );
}
