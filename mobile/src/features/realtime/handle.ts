import type { RealtimeClient } from './client';

/** The app's realtime connection while one exists (set by `RealtimeProvider`). */
export const realtimeHandle: { current: RealtimeClient | null } = { current: null };

const lastStart: Record<string, number> = {};

/**
 * Tell the other members whether I'm typing (docs/06 §4.1): `typing.start` at most every 3 s
 * while the draft has text, `typing.stop` once when it doesn't (sent, cleared, left the chat).
 * Silent without a connection: typing is a courtesy, never queued.
 */
export function reportTyping(
  conversationId: string,
  typing: boolean,
  now: number = Date.now(),
): void {
  const client = realtimeHandle.current;
  if (!client?.isOnline) {
    delete lastStart[conversationId];
    return;
  }
  if (typing) {
    const last = lastStart[conversationId];
    if (last === undefined || now - last >= 3000) {
      if (client.send('typing.start', { conversation_id: conversationId })) {
        lastStart[conversationId] = now;
      }
    }
    return;
  }
  if (lastStart[conversationId] !== undefined) {
    client.send('typing.stop', { conversation_id: conversationId });
    delete lastStart[conversationId];
  }
}
