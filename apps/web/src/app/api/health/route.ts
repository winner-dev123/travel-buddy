import { NextResponse } from 'next/server';
import { env } from '@/server/env';

export const dynamic = 'force-dynamic';

/** Liveness of the web process (does not call the platform). */
export function GET() {
  const e = env();
  return NextResponse.json(
    { status: 'ok', app_env: e.appEnv, api_mode: e.apiMode },
    { headers: { 'cache-control': 'no-store' } },
  );
}
