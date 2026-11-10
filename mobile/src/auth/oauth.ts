import * as Crypto from 'expo-crypto';
import * as Linking from 'expo-linking';
import * as WebBrowser from 'expo-web-browser';

import { type OAuthProvider, type SupabaseAuthClient, SupabaseAuthError } from './supabaseAuth';

/** The person closed the browser or went back: not an error to show. */
export class OAuthCancelled extends Error {
  override name = 'OAuthCancelled';
}

/** Where Supabase sends the browser back; must be listed in Supabase's redirect URLs. */
export function oauthRedirectUrl(): string {
  return Linking.createURL('auth-callback');
}

/** PKCE pair (RFC 7636, S256): a random verifier and its base64url SHA-256 challenge. */
export async function pkcePair(): Promise<{ verifier: string; challenge: string }> {
  const verifier = Array.from(Crypto.getRandomBytes(32), (b) =>
    b.toString(16).padStart(2, '0'),
  ).join('');
  const digest = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, verifier, {
    encoding: Crypto.CryptoEncoding.BASE64,
  });
  const challenge = digest.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return { verifier, challenge };
}

/** Query and fragment parameters of the redirect (Supabase reports errors in either). */
function redirectParams(url: string): URLSearchParams {
  const [beforeHash, hash = ''] = url.split('#');
  const query = beforeHash?.split('?')[1] ?? '';
  const params = new URLSearchParams(query);
  new URLSearchParams(hash).forEach((value, key) => params.set(key, value));
  return params;
}

/**
 * "Continue with Google / Apple" (AUTH-002, AUTH-003): the provider sign-in runs in the system
 * browser through Supabase; the app gets back a one-time code and exchanges it, with the PKCE
 * verifier only it holds, for the Supabase access token. That token is then exchanged for a
 * platform session exactly like a password sign-in (ADR-0020).
 */
export async function signInWithProvider(
  supabase: SupabaseAuthClient,
  provider: OAuthProvider,
): Promise<string> {
  const { verifier, challenge } = await pkcePair();
  const redirectTo = oauthRedirectUrl();
  const result = await WebBrowser.openAuthSessionAsync(
    supabase.authorizeUrl(provider, challenge, redirectTo),
    redirectTo,
  );
  if (result.type !== 'success') {
    throw new OAuthCancelled('Sign-in was cancelled.');
  }
  const params = redirectParams(result.url);
  const failure = params.get('error_description') ?? params.get('error');
  if (failure) {
    throw new SupabaseAuthError('unknown', failure);
  }
  const code = params.get('code');
  if (!code) {
    throw new SupabaseAuthError('unknown', 'The sign-in returned no code.');
  }
  return supabase.exchangeCode(code, verifier);
}
