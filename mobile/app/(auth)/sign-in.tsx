import { FeatureGate } from '@/components/FeatureGate';

/** SCR-001 Sign in / register via the OIDC identity provider (Phase 1). */
export default function SignInScreen() {
  return <FeatureGate feature="auth" />;
}
