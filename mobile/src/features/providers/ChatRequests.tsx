import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { Text, View } from 'react-native';

import { getApiClient } from '@/api';
import type { Conversation } from '@/features/messages/api';
import { useAppTheme } from '@/theme/useAppTheme';

import { requestsForChat } from './api';
import { RequestCard } from './components';

/** The latest request of a provider chat, pinned above the messages (ADR-0036): dates, party
 * size and status, with the way to accept, decline or review it. */
export function ChatRequests({ conversation }: { conversation: Conversation }) {
  const { t } = useTranslation();
  const theme = useAppTheme();
  const router = useRouter();
  const requests = useQuery({
    queryKey: ['providers', 'chat-requests', conversation.id],
    queryFn: () => requestsForChat(getApiClient(), conversation),
    staleTime: 30_000,
  });
  const latest = requests.data?.[0];
  if (!latest) return null;
  return (
    <View
      style={{ paddingHorizontal: theme.spacing[3], paddingTop: theme.spacing[2], gap: 4 }}
      testID="chat-provider-request"
    >
      <RequestCard
        inquiry={latest}
        showProvider={false}
        onPress={() =>
          router.push({ pathname: '/provider-requests/[id]', params: { id: latest.id } })
        }
      />
      {(requests.data?.length ?? 0) > 1 ? (
        <Text style={[theme.typography.caption, { color: theme.colors.textSecondary }]}>
          {t('providers.request.earlier', { count: (requests.data?.length ?? 1) - 1 })}
        </Text>
      ) : null}
    </View>
  );
}
