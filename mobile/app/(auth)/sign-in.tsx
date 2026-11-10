import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { mintDevIdToken } from '@/auth/devIdp';
import { describeAuthError } from '@/auth/errors';
import { FirebaseAuthClient } from '@/auth/firebaseAuth';
import { availableFirebaseSocial, signInWithFirebaseSocial } from '@/auth/firebaseSocial';
import {
  AuthProviderError,
  MIN_PASSWORD_LENGTH,
  type PasswordAuthClient,
} from '@/auth/identityClient';
import { OAuthCancelled, signInWithProvider } from '@/auth/oauth';
import { APP_INFO_KEY, exchangeIdToken, fetchAppInfo } from '@/auth/session';
import { takeHomeRoute } from '@/auth/sessionStore';
import { type OAuthProvider, SupabaseAuthClient } from '@/auth/supabaseAuth';
import { Button, Notice, TextField } from '@/components/Form';
import {
  getFirebaseConfig,
  getGoogleWebClientId,
  getIdentityProviderKind,
  getSupabaseConfig,
  type IdentityProviderKind,
} from '@/config/env';
import { i18n } from '@/i18n';
import { useAppTheme } from '@/theme/useAppTheme';

type Mode = 'signIn' | 'signUp';

/** The configured provider's client; null for the development IdP or a build missing settings. */
function passwordClient(provider: IdentityProviderKind): PasswordAuthClient | null {
  try {
    if (provider === 'firebase') {
      return new FirebaseAuthClient(getFirebaseConfig(), undefined, () => i18n.language);
    }
    return provider === 'supabase' ? new SupabaseAuthClient(getSupabaseConfig()) : null;
  } catch {
    return null;
  }
}

/** SCR-001 Sign in / create account (AUTH-001..003, ADR-0020, ADR-0028). */
export default function SignInScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const provider = getIdentityProviderKind();
  const [mode, setMode] = useState<Mode>('signIn');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  // After a sign-up, or when sign-in says the email isn't confirmed yet (SCR-002).
  const [canResend, setCanResend] = useState(false);
  // A build without the provider's settings shows an explicit error instead of crashing.
  const auth = useMemo(() => passwordClient(provider), [provider]);
  const usesPassword = provider !== 'dev';
  const misconfigured = usesPassword && auth === null;
  // AUTH-002/003: only the providers configured in the IdP, as announced by the API. Apple comes
  // first on iOS (App Store guideline 4.8: at least as prominent as other providers).
  const appInfo = useQuery({
    queryKey: APP_INFO_KEY,
    queryFn: () => fetchAppInfo(getApiClient()),
    enabled: auth !== null,
    staleTime: 5 * 60_000,
  });
  // AUTH-005: Firebase sends the reset email from here; Supabase's reset runs on the web. Either
  // way the new password then works here too.
  const resetUrl = auth?.supportsInAppReset ? null : (appInfo.data?.password_reset_url ?? null);
  // Firebase runs social sign-in through native sheets (BL-6.12): only what this build and device
  // can offer. Supabase runs it in the browser, so every announced provider works.
  const nativeSocial = useQuery({
    queryKey: ['auth', 'native-social'],
    queryFn: () => availableFirebaseSocial({ googleWebClientId: getGoogleWebClientId() }),
    enabled: auth instanceof FirebaseAuthClient,
    staleTime: Infinity,
  });
  const order: Record<OAuthProvider, number> =
    Platform.OS === 'ios' ? { apple: 0, google: 1 } : { google: 0, apple: 1 };
  const socialProviders = (auth ? (appInfo.data?.auth_providers ?? []) : [])
    .filter((p): p is OAuthProvider => p === 'google' || p === 'apple')
    .filter((p) => auth?.supportsSocial || (nativeSocial.data ?? []).includes(p))
    .sort((a, b) => order[a] - order[b]);

  async function finish(idToken: string): Promise<void> {
    const outcome = await exchangeIdToken(getApiClient(), idToken);
    if (outcome.kind === 'registration_required') {
      router.replace('/complete-registration');
    } else {
      // PROF-002: straight to the feed, unless setup was never finished.
      router.replace(outcome.me.onboarding_completed ? takeHomeRoute() : '/onboarding');
    }
  }

  async function submit(): Promise<void> {
    setError(null);
    setInfo(null);
    const trimmedEmail = email.trim();
    if (!trimmedEmail || (usesPassword && !password)) {
      setError(t('auth.errors.missingFields'));
      return;
    }
    if (usesPassword && mode === 'signUp' && password.length < MIN_PASSWORD_LENGTH) {
      setError(t('auth.errors.weak_password'));
      return;
    }
    setBusy(true);
    try {
      if (provider === 'dev') {
        await finish(
          await mintDevIdToken(getApiClient(), {
            email: trimmedEmail,
            name: name.trim() || 'Dev Traveler',
          }),
        );
        return;
      }
      if (!auth) {
        return;
      }
      if (mode === 'signUp') {
        const result = await auth.signUp(trimmedEmail, password);
        if (result.kind === 'confirmation_sent') {
          setInfo(t('auth.confirmationSent'));
          setCanResend(true);
          setMode('signIn');
          return;
        }
        await finish(result.accessToken);
        void auth.signOut(result.accessToken);
        return;
      }
      const idToken = await auth.signInWithPassword(trimmedEmail, password);
      try {
        await finish(idToken);
      } finally {
        // The provider's session was only needed for the exchange.
        void auth.signOut(idToken);
      }
    } catch (caught) {
      setError(describeAuthError(caught, t));
      if (caught instanceof AuthProviderError && caught.code === 'email_not_confirmed') {
        setCanResend(true);
      }
    } finally {
      setBusy(false);
    }
  }

  async function continueWith(social: OAuthProvider): Promise<void> {
    if (!auth) return;
    setError(null);
    setInfo(null);
    setBusy(true);
    try {
      const idToken =
        auth instanceof SupabaseAuthClient
          ? await signInWithProvider(auth, social)
          : auth instanceof FirebaseAuthClient
            ? await signInWithFirebaseSocial(auth, social, {
                googleWebClientId: getGoogleWebClientId(),
              })
            : null;
      if (!idToken) return;
      try {
        await finish(idToken);
      } finally {
        void auth.signOut(idToken);
      }
    } catch (caught) {
      if (!(caught instanceof OAuthCancelled)) {
        setError(describeAuthError(caught, t));
      }
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    if (!auth || email.trim().length === 0) return;
    if (!password) {
      setError(t('auth.errors.missingFields'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await auth.resendConfirmation(email.trim(), password);
      setInfo(t('auth.confirmationResent'));
    } catch (caught) {
      setError(describeAuthError(caught, t));
    } finally {
      setBusy(false);
    }
  }

  async function sendReset() {
    if (!auth) return;
    setError(null);
    setInfo(null);
    if (email.trim().length === 0) {
      setError(t('auth.errors.missingEmail'));
      return;
    }
    setBusy(true);
    try {
      await auth.sendPasswordReset(email.trim());
      setInfo(t('auth.resetSent'));
    } catch (caught) {
      setError(describeAuthError(caught, t));
    } finally {
      setBusy(false);
    }
  }

  const title =
    provider === 'dev'
      ? t('auth.devPersonaTitle')
      : mode === 'signIn'
        ? t('auth.signInTitle')
        : t('auth.createAccountTitle');

  return (
    <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
      <KeyboardAvoidingView
        style={styles.fill}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[4] }}
          keyboardShouldPersistTaps="handled"
          testID="sign-in-screen"
        >
          <Text
            accessibilityRole="header"
            style={[theme.typography.title1, { color: theme.colors.textPrimary }]}
          >
            {title}
          </Text>
          {provider === 'dev' ? <Notice tone="info">{t('auth.devPersonaHint')}</Notice> : null}
          {misconfigured ? (
            <Notice tone="error" testID="sign-in-misconfigured">
              {t('auth.errors.notConfigured')}
            </Notice>
          ) : null}
          {info ? (
            <Notice tone="success" testID="sign-in-info">
              {info}
            </Notice>
          ) : null}
          {error ? (
            <Notice tone="error" testID="sign-in-error">
              {error}
            </Notice>
          ) : null}
          {provider === 'dev' ? (
            <TextField
              label={t('auth.name')}
              value={name}
              onChangeText={setName}
              autoComplete="name"
              testID="sign-in-name"
            />
          ) : null}
          <TextField
            label={t('auth.email')}
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            autoComplete="email"
            keyboardType="email-address"
            textContentType="emailAddress"
            testID="sign-in-email"
          />
          {usesPassword ? (
            <TextField
              label={t('auth.password')}
              hint={mode === 'signUp' ? t('auth.passwordHint') : undefined}
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoComplete={mode === 'signUp' ? 'new-password' : 'current-password'}
              textContentType={mode === 'signUp' ? 'newPassword' : 'password'}
              testID="sign-in-password"
            />
          ) : null}
          <Button
            label={
              provider === 'dev'
                ? t('auth.continueDev')
                : mode === 'signIn'
                  ? t('auth.signIn')
                  : t('auth.createAccount')
            }
            onPress={() => void submit()}
            busy={busy}
            disabled={misconfigured}
            testID="sign-in-submit"
          />
          {usesPassword && mode === 'signIn' && (resetUrl || auth?.supportsInAppReset) ? (
            <Button
              variant="secondary"
              label={t('auth.forgotPassword')}
              onPress={() => void (resetUrl ? WebBrowser.openBrowserAsync(resetUrl) : sendReset())}
              disabled={busy}
              testID="sign-in-forgot-password"
            />
          ) : null}
          {usesPassword && canResend && mode === 'signIn' ? (
            <Button
              variant="secondary"
              label={t('auth.resendConfirmation')}
              onPress={() => void resend()}
              disabled={busy || email.trim().length === 0}
              testID="sign-in-resend"
            />
          ) : null}
          {socialProviders.length > 0 ? (
            <>
              <Text
                style={[
                  theme.typography.caption,
                  styles.center,
                  { color: theme.colors.textSecondary },
                ]}
              >
                {t('auth.or')}
              </Text>
              {socialProviders.map((social) => (
                <Button
                  key={social}
                  variant="secondary"
                  label={social === 'apple' ? t('auth.continueApple') : t('auth.continueGoogle')}
                  onPress={() => void continueWith(social)}
                  disabled={busy}
                  testID={`sign-in-${social}`}
                />
              ))}
            </>
          ) : null}
          {usesPassword ? (
            <Button
              variant="secondary"
              label={mode === 'signIn' ? t('auth.switchToSignUp') : t('auth.switchToSignIn')}
              onPress={() => {
                setMode(mode === 'signIn' ? 'signUp' : 'signIn');
                setError(null);
              }}
              disabled={busy}
              testID="sign-in-switch-mode"
            />
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 }, center: { textAlign: 'center' } });
