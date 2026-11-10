import { useQuery } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Notice } from '@/components/Form';
import { getGuide, type GuideSection } from '@/features/explore/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** Plain text from the small Markdown subset guides use (emphasis markers are dropped). */
function plain(markdown: string): string {
  return markdown.replace(/\*\*(.+?)\*\*/g, '$1').replace(/\*(.+?)\*/g, '$1');
}

/** SCR-045 Guide reader: structured sections and FAQs, with the content's license (GUIDE-004). */
export default function GuideScreen() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const guide = useQuery({ queryKey: ['guides', id], queryFn: () => getGuide(getApiClient(), id) });
  const locked =
    guide.error instanceof ApiProblem &&
    (guide.error.code === 'entitlement_required' || guide.error.code === 'unauthenticated');
  const data = guide.data;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: data?.title ?? t('guides.title') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {locked ? <Notice tone="info">{t('guides.locked')}</Notice> : null}
        {guide.isError && !locked ? <Notice tone="error">{t('guides.missing')}</Notice> : null}
        {data ? (
          <>
            <Text
              accessibilityRole="header"
              style={[theme.typography.title2, { color: theme.colors.textPrimary }]}
            >
              {data.title}
            </Text>
            <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
              {data.summary}
            </Text>
            {data.sections.map((section) => (
              <Section key={section.id} section={section} />
            ))}
            <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
              {t('guides.attribution', { source: data.attribution ?? data.content_license })}
            </Text>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function Section({ section }: { section: GuideSection }) {
  const theme = useAppTheme();
  const paragraphs = section.body_markdown.split(/\n{2,}/).filter((p) => p.trim().length > 0);
  return (
    <View style={{ gap: theme.spacing[2] }} testID={`guide-section-${section.id}`}>
      <Text
        accessibilityRole="header"
        style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
      >
        {section.heading}
      </Text>
      {paragraphs.map((paragraph, index) => (
        <Text key={index} style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
          {plain(
            paragraph
              .split('\n')
              .map((line) => (line.startsWith('- ') ? `•  ${line.slice(2)}` : line))
              .join('\n'),
          )}
        </Text>
      ))}
      {(section.faq_items ?? []).map((item) => (
        <View key={item.question} style={{ gap: theme.spacing[1] }}>
          <Text style={[theme.typography.bodyStrong, { color: theme.colors.textPrimary }]}>
            {item.question}
          </Text>
          <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
            {plain(item.answer_markdown)}
          </Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
});
