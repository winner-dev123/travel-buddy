/** Subset of the contract's `Me`, `AuthResult` and `SessionTokens` schemas used by the app. */

export interface SessionTokens {
  token_type: 'Bearer';
  access_token: string;
  access_token_expires_at: string;
  refresh_token: string;
  refresh_token_expires_at: string;
  session_id: string;
}

export interface Me {
  account: {
    id: string;
    email: string | null;
    email_verified: boolean;
    status: 'active' | 'pending_deletion';
    primary_locale: string;
  };
  profile: {
    id: string;
    handle: string;
    display_name: string;
    bio: string | null;
    account_visibility: 'public' | 'private';
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
