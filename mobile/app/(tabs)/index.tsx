import { FeatureGate } from '@/components/FeatureGate';

/** SCR-020 Home: destination-based travel feed (Phase 1). */
export default function HomeScreen() {
  return <FeatureGate feature="feed" />;
}
