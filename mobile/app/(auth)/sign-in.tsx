import { useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { mintDevIdToken } from '@/auth/devIdp';
import { describeAuthError } from '@/auth/errors';
import { exchangeIdToken } from '@/auth/session';
import { SupabaseAuthClient } from '@/auth/supabaseAuth';
import { Button, Notice, TextField } from '@/components/Form';
import { getIdentityProviderKind, getSupabaseConfig } from '@/config/env';
import { useAppTheme } from '@/theme/useAppTheme';

type Mode = 'signIn' | 'signUp';

/** SCR-001 Sign in / create account (AUTH-001..003, ADR-0020). */
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
  // A build without Supabase settings shows an explicit error instead of crashing.
  const supabase = useMemo(() => {
    if (provider !== 'supabase') {
      return null;
    }
    try {
      return new SupabaseAuthClient(getSupabaseConfig());
    } catch {
      return null;
    }
  }, [provider]);
  const misconfigured = provider === 'supabase' && supabase === null;

  async function finish(idToken: string): Promise<void> {
    const outcome = await exchangeIdToken(getApiClient(), idToken);
    if (outcome.kind === 'registration_required') {
      router.replace('/complete-registration');
    } else {
      // PROF-002: straight to the feed, unless setup was never finished.
      router.replace(outcome.me.onboarding_completed ? '/' : '/onboarding');
    }
  }

  async function submit(): Promise<void> {
    setError(null);
    setInfo(null);
    const trimmedEmail = email.trim();
    if (!trimmedEmail || (provider === 'supabase' && !password)) {
      setError(t('auth.errors.missingFields'));
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
      if (!supabase) {
        return;
      }
      if (mode === 'signUp') {
        const result = await supabase.signUp(trimmedEmail, password);
        if (result.kind === 'confirmation_sent') {
          setInfo(t('auth.confirmationSent'));
          setMode('signIn');
          return;
        }
        await finish(result.accessToken);
        void supabase.signOut(result.accessToken);
        return;
      }
      const accessToken = await supabase.signInWithPassword(trimmedEmail, password);
      try {
        await finish(accessToken);
      } finally {
        // The Supabase session was only needed for the exchange.
        void supabase.signOut(accessToken);
      }
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
          {provider === 'supabase' ? (
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
          {provider === 'supabase' ? (
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

const styles = StyleSheet.create({ fill: { flex: 1 } });
