import * as Crypto from 'expo-crypto';
import { Platform } from 'react-native';

import { type FirebaseAuthClient, FirebaseAuthError } from './firebaseAuth';
import { OAuthCancelled } from './oauth';
import type { OAuthProvider } from './supabaseAuth';

/**
 * "Continue with Google / Apple" through Firebase Authentication (AUTH-002, AUTH-003, BL-6.12).
 * The native sign-in sheet returns the provider's ID token, Firebase exchanges it
 * (`accounts:signInWithIdp`) for its own ID token, and that is exchanged for a platform session
 * like a password sign-in. The native modules are absent from Expo Go and from builds made before
 * they were added, so they load lazily and a missing module only hides the button.
 */

export interface FirebaseSocialConfig {
  /** The project's OAuth "Web client" ID: Google signs the ID token for this audience. */
  googleWebClientId: string | null;
}

type GoogleModule = typeof import('@react-native-google-signin/google-signin');
type AppleModule = typeof import('expo-apple-authentication');

/* eslint-disable @typescript-eslint/no-require-imports -- lazy on purpose: a native module missing
   from this build (Expo Go, older builds) throws when loaded, which must only hide its button. */
function loadGoogle(): GoogleModule | null {
  try {
    return require('@react-native-google-signin/google-signin') as GoogleModule;
  } catch {
    return null;
  }
}

function loadApple(): AppleModule | null {
  try {
    return require('expo-apple-authentication') as AppleModule;
  } catch {
    return null;
  }
}
/* eslint-enable @typescript-eslint/no-require-imports */

/** The social providers this build and device can offer. */
export async function availableFirebaseSocial(
  config: FirebaseSocialConfig,
): Promise<OAuthProvider[]> {
  const available: OAuthProvider[] = [];
  if (Platform.OS === 'ios') {
    const apple = loadApple();
    if (apple && (await apple.isAvailableAsync().catch(() => false))) {
      available.push('apple');
    }
  }
  if (config.googleWebClientId && loadGoogle()) {
    available.push('google');
  }
  return available;
}

export async function signInWithFirebaseSocial(
  client: FirebaseAuthClient,
  provider: OAuthProvider,
  config: FirebaseSocialConfig,
): Promise<string> {
  return provider === 'google' ? google(client, config) : apple(client);
}

function unavailable(): FirebaseAuthError {
  return new FirebaseAuthError('unknown', 'This sign-in method is not available in this build.');
}

async function google(client: FirebaseAuthClient, config: FirebaseSocialConfig): Promise<string> {
  const module = loadGoogle();
  if (!module || !config.googleWebClientId) {
    throw unavailable();
  }
  const { GoogleSignin, isErrorWithCode, isSuccessResponse, statusCodes } = module;
  GoogleSignin.configure({ webClientId: config.googleWebClientId });
  let idToken: string | null;
  try {
    await GoogleSignin.hasPlayServices({ showPlayServicesUpdateDialog: true });
    const response = await GoogleSignin.signIn();
    if (!isSuccessResponse(response)) {
      throw new OAuthCancelled('Sign-in was cancelled.');
    }
    idToken = response.data.idToken;
  } catch (caught) {
    if (caught instanceof OAuthCancelled) throw caught;
    if (isErrorWithCode(caught) && caught.code === statusCodes.SIGN_IN_CANCELLED) {
      throw new OAuthCancelled('Sign-in was cancelled.');
    }
    throw new FirebaseAuthError(
      'unknown',
      caught instanceof Error ? caught.message : 'Google sign-in failed.',
    );
  } finally {
    // Show the account chooser every time: a shared phone must not reuse the last account.
    GoogleSignin.signOut().catch(() => undefined);
  }
  if (!idToken) {
    throw new FirebaseAuthError('unknown', 'Google returned no ID token.');
  }
  return client.signInWithIdp('google.com', idToken);
}

async function apple(client: FirebaseAuthClient): Promise<string> {
  const module = loadApple();
  if (!module || Platform.OS !== 'ios') {
    throw unavailable();
  }
  // Apple signs the SHA-256 of the nonce; Firebase checks it against the raw value.
  const rawNonce = Array.from(Crypto.getRandomBytes(16), (b) =>
    b.toString(16).padStart(2, '0'),
  ).join('');
  const hashedNonce = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, rawNonce);
  let identityToken: string | null;
  try {
    const credential = await module.signInAsync({
      requestedScopes: [
        module.AppleAuthenticationScope.FULL_NAME,
        module.AppleAuthenticationScope.EMAIL,
      ],
      nonce: hashedNonce,
    });
    identityToken = credential.identityToken;
  } catch (caught) {
    if ((caught as { code?: unknown }).code === 'ERR_REQUEST_CANCELED') {
      throw new OAuthCancelled('Sign-in was cancelled.');
    }
    throw new FirebaseAuthError(
      'unknown',
      caught instanceof Error ? caught.message : 'Apple sign-in failed.',
    );
  }
  if (!identityToken) {
    throw new FirebaseAuthError('unknown', 'Apple returned no identity token.');
  }
  return client.signInWithIdp('apple.com', identityToken, rawNonce);
}
