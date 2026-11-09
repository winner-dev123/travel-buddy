import { DiscoverySafetyNotice } from '@/components/DiscoverySafetyNotice';
import { FeatureGate } from '@/components/FeatureGate';

/**
 * SCR-060 Companions: opt-in traveler discovery, connection requests, groups
 * (Phase 2–3). The safety guidance is real copy and is shown even now.
 */
export default function CompanionsScreen() {
  return <FeatureGate feature="companions" placeholderExtra={<DiscoverySafetyNotice />} />;
}
