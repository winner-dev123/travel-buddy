import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getApiClient } from '@/api';
import { Button, Notice, SwitchRow, TextField } from '@/components/Form';
import {
  REPORT_REASONS,
  report,
  type ReportReason,
  type ReportTarget,
} from '@/features/account/api';
import { feedKeys } from '@/features/feed/api';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-130 Report (SAFE-002): reason, optional details, optional block in the same step. */
export default function ReportScreen() {
  const params = useLocalSearchParams<{ type: ReportTarget; target: string; name?: string }>();
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState<ReportReason | null>(null);
  const [details, setDetails] = useState('');
  const [alsoBlock, setAlsoBlock] = useState(false);

  const send = useMutation({
    mutationFn: () =>
      report(getApiClient(), {
        targetType: params.type,
        targetId: params.target,
        reason: reason ?? 'other',
        details,
        alsoBlock,
      }),
    onSuccess: () => {
      if (alsoBlock) void queryClient.invalidateQueries({ queryKey: feedKeys.all });
    },
  });

  if (send.isSuccess) {
    return (
      <SafeAreaView style={[styles.fill, { backgroundColor: theme.colors.background }]}>
        <Stack.Screen options={{ headerShown: true, title: t('report.title') }} />
        <View style={{ padding: theme.spacing[6], gap: theme.spacing[4] }} testID="report-done">
          <Notice tone="success">{t('report.thanks')}</Notice>
          <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
            {t('report.next')}
          </Text>
          <Button label={t('report.close')} onPress={() => router.back()} testID="report-close" />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('report.title') }} />
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[6], gap: theme.spacing[3] }}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
          {t(`report.question.${params.type}`)}
        </Text>
        <View accessibilityRole="radiogroup" style={{ gap: theme.spacing[2] }}>
          {REPORT_REASONS.map((value) => {
            const selected = value === reason;
            return (
              <Pressable
                key={value}
                onPress={() => setReason(value)}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                style={[
                  styles.option,
                  {
                    borderColor: selected ? theme.colors.primary : theme.colors.borderStrong,
                    backgroundColor: selected ? theme.colors.infoSurface : theme.colors.background,
                  },
                ]}
                testID={`report-reason-${value}`}
              >
                <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
                  {t(`report.reasons.${value}`)}
                </Text>
              </Pressable>
            );
          })}
        </View>
        {reason === 'minor_safety' || reason === 'self_harm' ? (
          <Notice tone="info">{t('report.urgent')}</Notice>
        ) : null}
        <TextField
          label={t('report.details')}
          value={details}
          onChangeText={setDetails}
          maxLength={1000}
          multiline
          testID="report-details"
        />
        <SwitchRow
          label={
            params.name ? t('report.alsoBlockName', { name: params.name }) : t('report.alsoBlock')
          }
          value={alsoBlock}
          onValueChange={setAlsoBlock}
          testID="report-also-block"
        />
        {send.isError ? <Notice tone="error">{t('report.failed')}</Notice> : null}
        <Button
          label={t('report.submit')}
          onPress={() => send.mutate()}
          disabled={reason === null}
          busy={send.isPending}
          testID="report-submit"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  option: { borderWidth: 1, borderRadius: 8, padding: 12, minHeight: 44 },
});
