import NetInfo from '@react-native-community/netinfo';
import { useQueryClient } from '@tanstack/react-query';
import { randomUUID } from 'expo-crypto';
import { useEffect } from 'react';
import { AppState } from 'react-native';

import { getApiClient } from '@/api';
import { APP_VERSION, clientPlatform, refreshAccessToken } from '@/auth/session';
import { useSessionStore } from '@/auth/sessionStore';
import { tokenStore } from '@/auth/tokenStore';
import { useBannerStore } from '@/components/InAppBanner';
import { getApiBaseUrl } from '@/config/env';
import { forgetCachedChats } from '@/features/messages/chatCache';
import { sendQueuedMessages, settleMessage, useOutboxStore } from '@/features/messages/outbox';
import { isOnlineState } from '@/offline/connectivity';

import { applyFrame, syncRequest, type LiveNotification } from './apply';
import { RealtimeClient, realtimeUrl } from './client';
import { realtimeHandle } from './handle';
import { useRealtimeStore } from './store';

const OUTBOX_TICK_MS = 4000;

/** The href a live notification opens, when it has one. */
function bannerHref(notification: LiveNotification) {
  if (notification.type === 'connection_request') return '/(tabs)/companions' as const;
  if (notification.type === 'connection_accepted' && notification.actor) {
    return { pathname: '/user/[id]' as const, params: { id: notification.actor.id } };
  }
  return '/notifications' as const;
}

/**
 * Keeps the realtime connection (ADR-0033) while signed in and in the foreground, applies what
 * arrives to the cached data, and sends queued messages whenever a connection is available.
 * Renders nothing; mount it once near the root.
 */
export function RealtimeConnection() {
  const queryClient = useQueryClient();
  const signedIn = useSessionStore((state) => state.status === 'signed_in');
  const signedOut = useSessionStore((state) => state.status === 'signed_out');

  // Signed out (or the saved session turned out to be gone): no one else's chats stay in memory.
  useEffect(() => {
    if (signedOut) forgetCachedChats(queryClient);
  }, [signedOut, queryClient]);

  useEffect(() => {
    if (!signedIn) return;
    const flush = () => void sendQueuedMessages(queryClient);
    const client = new RealtimeClient({
      url: realtimeUrl(getApiBaseUrl()),
      getToken: () => tokenStore.getAccessToken(),
      refreshToken: () => refreshAccessToken(getApiClient()),
      client: clientPlatform(),
      appVersion: APP_VERSION,
      newId: randomUUID,
      onStatus: (status) => {
        useRealtimeStore.getState().setStatus(status);
        if (status === 'online') {
          client.send('sync.request', { conversations: syncRequest(queryClient) });
          flush();
        }
      },
      onFrame: (frame) =>
        applyFrame(frame, {
          queryClient,
          me: useSessionStore.getState().me?.account.id,
          onOwnMessage: (clientMessageId) => settleMessage(clientMessageId),
          onNotification: (notification) => {
            if (
              notification.type !== 'connection_request' &&
              notification.type !== 'connection_accepted'
            ) {
              return;
            }
            useBannerStore.getState().show({
              id: notification.id,
              title: notification.title,
              body: notification.body,
              user: notification.actor ? { ...notification.actor, avatar: null } : null,
              href: bannerHref(notification),
            });
          },
        }),
    });
    realtimeHandle.current = client;
    if (AppState.currentState !== 'background') client.start();

    const appState = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        client.start();
        client.reconnectNow();
        flush();
      } else if (state === 'background') {
        client.stop();
      }
    });
    const network = NetInfo.addEventListener((state) => {
      if (isOnlineState(state)) {
        client.reconnectNow();
        flush();
      }
    });
    const ticker = setInterval(() => {
      useRealtimeStore.getState().prune(Date.now());
      if (useOutboxStore.getState().items.some((item) => item.status === 'sending')) flush();
    }, OUTBOX_TICK_MS);

    return () => {
      clearInterval(ticker);
      network();
      appState.remove();
      client.stop();
      if (realtimeHandle.current === client) realtimeHandle.current = null;
      useRealtimeStore.getState().setStatus('idle');
    };
  }, [signedIn, queryClient]);

  return null;
}
