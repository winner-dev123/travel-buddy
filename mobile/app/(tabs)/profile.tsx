import { FeatureGate } from '@/components/FeatureGate';

/** SCR-100 Profile: posts, saved content, trips, settings (Phase 1). */
export default function ProfileScreen() {
  return <FeatureGate feature="profile" />;
}
