import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice, SwitchRow, TextField } from '@/components/Form';
import { ServerFeature } from '@/features/flags/serverFlags';
import { getProvider, providerKeys, sendRequest } from '@/features/providers/api';
import { SafetyTips } from '@/features/providers/components';
import { isIsoDate, isoDaysFromToday } from '@/features/providers/format';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-163 Send a request to a guide or company; it opens the provider chat (PROV-009). */
export default function RequestScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <RequestForm />
    </ServerFeature>
  );
}

function RequestForm() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { providerId, offeringId } = useLocalSearchParams<{
    providerId: string;
    offeringId?: string;
  }>();
  const provider = useQuery({
    queryKey: providerKeys.profile(providerId),
    queryFn: () => getProvider(getApiClient(), providerId),
  });
  const [flexible, setFlexible] = useState(false);
  const [start, setStart] = useState(isoDaysFromToday(7));
  const [end, setEnd] = useState('');
  const [people, setPeople] = useState('2');
  const [message, setMessage] = useState('');
  // The same form keeps its key, so a retry after a lost response never sends it twice; an
  // edited form is a new request and gets a new key.
  const [key, setKey] = useState(() => getApiClient().newIdempotencyKey());
  const edited =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      set(value);
      setKey(getApiClient().newIdempotencyKey());
    };

  const partySize = Number.parseInt(people, 10);
  const datesOk =
    flexible ||
    (isIsoDate(start) &&
      start >= isoDaysFromToday(0) &&
      (!end || (isIsoDate(end) && end >= start)));
  const valid =
    datesOk &&
    Number.isInteger(partySize) &&
    partySize >= 1 &&
    partySize <= 50 &&
    message.trim().length >= 10;

  const send = useMutation({
    mutationFn: () =>
      sendRequest(getApiClient(), providerId, key, {
        offering_id: offeringId ?? null,
        flexible_dates: flexible,
        start_date: flexible ? null : start,
        end_date: !flexible && end ? end : null,
        party_size: partySize,
        message: message.trim(),
      }),
    onSuccess: (inquiry) => {
      void queryClient.invalidateQueries({ queryKey: providerKeys.myRequests });
      router.replace({ pathname: '/provider-requests/[id]', params: { id: inquiry.id } });
    },
  });
  const problem = send.error instanceof ApiProblem ? send.error.code : send.error ? 'failed' : null;
  const problemText =
    problem === 'inquiry_already_open'
      ? t('providers.request.alreadyOpen')
      : problem === 'rate_limited'
        ? t('providers.request.tooMany')
        : problem === 'email_unverified'
          ? t('providers.request.verifyEmail')
          : problem
            ? t('providers.request.failed')
            : null;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('providers.request.title') }} />
      <ScrollView
        contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}
        keyboardShouldPersistTaps="handled"
      >
        {provider.data ? (
          <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
            {t('providers.request.to', { name: provider.data.display_name })}
          </Text>
        ) : null}
        <SafetyTips />
        <SwitchRow
          label={t('providers.request.flexibleDates')}
          value={flexible}
          onValueChange={edited(setFlexible)}
          testID="request-flexible"
        />
        {!flexible ? (
          <View style={{ gap: theme.spacing[2] }}>
            <TextField
              label={t('providers.request.start')}
              hint={t('providers.request.dateHint')}
              value={start}
              onChangeText={edited(setStart)}
              autoCapitalize="none"
              autoCorrect={false}
              maxLength={10}
              testID="request-start"
            />
            <TextField
              label={t('providers.request.end')}
              hint={t('providers.request.endHint')}
              value={end}
              onChangeText={edited(setEnd)}
              autoCapitalize="none"
              autoCorrect={false}
              maxLength={10}
              testID="request-end"
            />
          </View>
        ) : null}
        <TextField
          label={t('providers.request.party')}
          value={people}
          onChangeText={edited(setPeople)}
          keyboardType="number-pad"
          maxLength={2}
          testID="request-party"
        />
        <TextField
          label={t('providers.request.message')}
          hint={t('providers.request.messageHint')}
          value={message}
          onChangeText={edited(setMessage)}
          multiline
          maxLength={2000}
          testID="request-message"
        />
        <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
          {t('providers.request.paymentNote')}
        </Text>
        {problemText ? (
          <Notice tone="error" testID="request-error">
            {problemText}
          </Notice>
        ) : null}
        <Button
          label={t('providers.request.submit')}
          onPress={() => send.mutate()}
          disabled={!valid}
          busy={send.isPending}
          testID="request-submit"
        />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
