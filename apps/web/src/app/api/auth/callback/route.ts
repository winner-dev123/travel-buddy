import { NextResponse, type NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';

/**
 * OIDC redirect URI. The OIDC adapter is not implemented yet (docs/web/09-backlog.md), so this
 * never creates a session; it sends the user back to the login page with an explicit error.
 */
export async function GET(request: NextRequest) {
  return NextResponse.redirect(new URL('/login?error=provider_unavailable', request.url), 303);
}
