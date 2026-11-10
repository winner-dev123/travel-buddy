import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { ApiProblem, getApiClient } from '@/api';
import { useAppTheme } from '@/theme/useAppTheme';

import { allowTranslation, translatePost } from './api';

function primary(tag: string): string {
  return tag.split('-')[0]!.toLowerCase();
}

function languageName(tag: string, locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: 'language' }).of(tag) ?? tag;
  } catch {
    return tag;
  }
}

type State =
  | { kind: 'original' }
  | { kind: 'loading' }
  | { kind: 'translated'; text: string }
  | { kind: 'consent' }
  | { kind: 'failed' };

/**
 * A post's text with an optional machine translation (POST-010, I18N-006): offered when the post is
 * in another language, always labelled as machine-translated, and the original is one tap away.
 */
export function TranslatableBody({
  post,
  enabled,
}: {
  post: { id: string; body: string; language: string };
  enabled: boolean;
}) {
  const { t, i18n } = useTranslation();
  const theme = useAppTheme();
  const [state, setState] = useState<State>({ kind: 'original' });
  const target = i18n.language;
  const offer =
    enabled && post.body.trim().length > 0 && primary(post.language) !== primary(target);

  const translate = async () => {
    setState({ kind: 'loading' });
    try {
      const result = await translatePost(getApiClient(), post.id, target);
      setState({ kind: 'translated', text: result.text });
    } catch (error) {
      setState(
        error instanceof ApiProblem && error.code === 'consent_required'
          ? { kind: 'consent' }
          : { kind: 'failed' },
      );
    }
  };
  const allow = async () => {
    try {
      await allowTranslation(getApiClient());
    } catch {
      setState({ kind: 'failed' });
      return;
    }
    await translate();
  };

  const link = (label: string, onPress: () => void, testID: string) => (
    <Pressable onPress={onPress} accessibilityRole="button" hitSlop={8} testID={testID}>
      <Text style={[theme.typography.caption, { color: theme.colors.primary }]}>{label}</Text>
    </Pressable>
  );

  return (
    <View style={styles.wrap}>
      <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
        {state.kind === 'translated' ? state.text : post.body}
      </Text>
      {!offer ? null : state.kind === 'translated' ? (
        <View style={styles.row}>
          <Text
            style={[theme.typography.caption, { color: theme.colors.textSecondary }]}
            testID={`post-translated-${post.id}`}
          >
            {t('post.translatedFrom', { language: languageName(post.language, target) })}
          </Text>
          {link(
            t('post.showOriginal'),
            () => setState({ kind: 'original' }),
            `post-original-${post.id}`,
          )}
        </View>
      ) : state.kind === 'consent' ? (
        <View style={styles.row}>
          <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
            {t('post.translationConsent')}
          </Text>
          {link(
            t('post.allowTranslation'),
            () => void allow(),
            `post-allow-translation-${post.id}`,
          )}
        </View>
      ) : state.kind === 'loading' ? (
        <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
          {t('post.translating')}
        </Text>
      ) : (
        <View style={styles.row}>
          {state.kind === 'failed' ? (
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('post.translationFailed')}
            </Text>
          ) : null}
          {link(t('post.translate'), () => void translate(), `post-translate-${post.id}`)}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 4 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' },
});
