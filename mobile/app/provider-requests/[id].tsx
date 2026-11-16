import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiProblem, getApiClient } from '@/api';
import { Button, Notice, TextField } from '@/components/Form';
import { ServerFeature } from '@/features/flags/serverFlags';
import {
  actionsFor,
  actOnRequest,
  getRequest,
  providerKeys,
  reviewRequest,
  type Inquiry,
  type InquiryAction,
} from '@/features/providers/api';
import { RequestCard } from '@/features/providers/components';
import { useAppTheme } from '@/theme/useAppTheme';

/** SCR-165 One request, for the traveler or the provider's team: status, chat, next step,
 * and the review once it's done (PROV-010, PROV-011). */
export default function RequestDetailScreen() {
  return (
    <ServerFeature anyOf={['provider_marketplace']}>
      <RequestDetail />
    </ServerFeature>
  );
}

function RequestDetail() {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { id } = useLocalSearchParams<{ id: string }>();
  const [rating, setRating] = useState(0);
  const [review, setReview] = useState('');
  const request = useQuery({
    queryKey: providerKeys.request(id),
    queryFn: () => getRequest(getApiClient(), id),
  });
  const refresh = (updated: Inquiry) => {
    queryClient.setQueryData(providerKeys.request(id), updated);
    void queryClient.invalidateQueries({ queryKey: providerKeys.myRequests, exact: true });
    void queryClient.invalidateQueries({ queryKey: ['providers', 'inbox'] });
  };
  const act = useMutation({
    mutationFn: ({ action, reason }: { action: InquiryAction; reason?: string }) =>
      actOnRequest(getApiClient(), id, action, reason),
    onSuccess: refresh,
  });
  const send = useMutation({
    mutationFn: () => reviewRequest(getApiClient(), id, rating, review),
    onSuccess: () => void request.refetch(),
  });
  const data = request.data;

  const confirm = (action: InquiryAction) => {
    if (action === 'accept' || action === 'complete') {
      act.mutate({ action });
      return;
    }
    Alert.alert(t(`providers.actions.${action}Title`), t(`providers.actions.${action}Body`), [
      { text: t('common.cancel'), style: 'cancel' },
      {
        text: t(`providers.actions.${action}`),
        style: 'destructive',
        onPress: () => act.mutate({ action }),
      },
    ]);
  };
  const failed =
    act.error instanceof ApiProblem && act.error.code === 'inquiry_transition_invalid'
      ? t('providers.actions.stale')
      : act.error
        ? t('providers.actions.failed')
        : null;

  return (
    <SafeAreaView
      edges={['bottom']}
      style={[styles.fill, { backgroundColor: theme.colors.background }]}
    >
      <Stack.Screen options={{ headerShown: true, title: t('providers.request.cardTitle') }} />
      <ScrollView contentContainerStyle={{ padding: theme.spacing[4], gap: theme.spacing[3] }}>
        {request.isError ? <Notice tone="error">{t('providers.request.missing')}</Notice> : null}
        {data ? (
          <>
            <RequestCard inquiry={data} />
            <Text style={[theme.typography.body, { color: theme.colors.textPrimary }]}>
              {data.message}
            </Text>
            {data.status === 'declined' && data.decline_reason ? (
              <Notice tone="info">
                {t('providers.request.declined', { reason: data.decline_reason })}
              </Notice>
            ) : null}
            {data.status === 'accepted' && data.viewer_side === 'traveler' ? (
              <Notice tone="success">{t('providers.request.acceptedNote')}</Notice>
            ) : null}
            {data.conversation_id ? (
              <Button
                label={t('providers.request.openChat')}
                icon="chatbubble-ellipses-outline"
                variant="secondary"
                onPress={() =>
                  router.push({
                    pathname: '/chat/[id]',
                    params: { id: data.conversation_id as string },
                  })
                }
                testID="request-open-chat"
              />
            ) : null}
            {data.viewer_side === 'traveler' ? (
              <Pressable
                onPress={() =>
                  router.push({ pathname: '/providers/[id]', params: { id: data.provider.id } })
                }
                accessibilityRole="link"
              >
                <Text style={[theme.typography.label, { color: theme.colors.primary }]}>
                  {t('providers.request.viewProvider', { name: data.provider.display_name })}
                </Text>
              </Pressable>
            ) : null}
            <View style={{ gap: theme.spacing[2] }}>
              {actionsFor(data).map((action) => (
                <Button
                  key={action}
                  label={t(`providers.actions.${action}`)}
                  variant={action === 'accept' || action === 'complete' ? 'primary' : 'secondary'}
                  onPress={() => confirm(action)}
                  busy={act.isPending && act.variables?.action === action}
                  testID={`request-${action}`}
                />
              ))}
            </View>
            {failed ? <Notice tone="error">{failed}</Notice> : null}

            {data.can_review ? (
              <View style={{ gap: theme.spacing[2] }} testID="request-review">
                <Text
                  accessibilityRole="header"
                  style={[theme.typography.title3, { color: theme.colors.textPrimary }]}
                >
                  {t('providers.review.title', { name: data.provider.display_name })}
                </Text>
                <View style={styles.stars} accessibilityRole="radiogroup">
                  {[1, 2, 3, 4, 5].map((value) => (
                    <Pressable
                      key={value}
                      onPress={() => setRating(value)}
                      accessibilityRole="radio"
                      accessibilityState={{ selected: rating === value }}
                      accessibilityLabel={t('providers.review.stars', { count: value })}
                      hitSlop={6}
                      testID={`review-star-${value}`}
                    >
                      <Text style={{ fontSize: 30, color: theme.colors.primary }}>
                        {value <= rating ? '★' : '☆'}
                      </Text>
                    </Pressable>
                  ))}
                </View>
                <TextField
                  label={t('providers.review.body')}
                  value={review}
                  onChangeText={setReview}
                  multiline
                  maxLength={2000}
                  testID="review-body"
                />
                {send.isError ? <Notice tone="error">{t('providers.review.failed')}</Notice> : null}
                <Button
                  label={t('providers.review.submit')}
                  onPress={() => send.mutate()}
                  disabled={rating === 0}
                  busy={send.isPending}
                  testID="review-submit"
                />
              </View>
            ) : null}
            {data.review_id ? <Notice tone="success">{t('providers.review.thanks')}</Notice> : null}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  stars: { flexDirection: 'row', gap: 8 },
});
