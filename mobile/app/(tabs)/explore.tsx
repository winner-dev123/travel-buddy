import { FeatureGate } from '@/components/FeatureGate';

/** SCR-040 Explore: map discovery, attractions, AI planner entry (Phase 4). */
export default function ExploreScreen() {
  return <FeatureGate feature="explore" />;
}
