import { FeatureGate } from '@/components/FeatureGate';

/** SCR-080 Messages: direct messages, group chats, group activities (Phase 3). */
export default function MessagesScreen() {
  return <FeatureGate feature="messaging" />;
}
