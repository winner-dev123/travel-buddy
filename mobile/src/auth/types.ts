/** Subset of the contract's `Me`, `AuthResult` and `SessionTokens` schemas used by the app. */

export interface SessionTokens {
  token_type: 'Bearer';
  access_token: string;
  access_token_expires_at: string;
  refresh_token: string;
  refresh_token_expires_at: string;
  session_id: string;
}

export type RestrictionKind =
  | 'posting_limited'
  | 'commenting_limited'
  | 'messaging_limited'
  | 'connection_requests_limited'
  | 'discovery_disabled'
  | 'media_upload_limited';

export interface AccountRestriction {
  kind: RestrictionKind;
  reason_code: string;
  until: string | null;
  appealable: boolean;
}

export interface Me {
  account: {
    id: string;
    email: string | null;
    email_verified: boolean;
    status: 'active' | 'pending_deletion';
    primary_locale: string;
    deletion_scheduled_for?: string | null;
    restrictions?: AccountRestriction[];
  };
  profile: {
    id: string;
    handle: string;
    display_name: string;
    bio: string | null;
    account_visibility: 'public' | 'private';
    avatar?: { id: string; status: string; url: string | null } | null;
  };
  preferences: { ui_locale: string; time_zone: string };
  privacy: { discovery_enabled: boolean; search_engine_indexing: boolean };
  roles: string[];
  onboarding_completed: boolean;
}

export interface AuthResult {
  tokens: SessionTokens;
  user: Me;
  is_new_user: boolean;
}

export interface LegalDocuments {
  terms_version: string;
  privacy_version: string;
  terms_url: string;
  privacy_url: string;
}
