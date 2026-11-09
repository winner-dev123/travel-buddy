/**
 * Named aliases over the GENERATED contract types (`generated.ts`, from
 * contracts/openapi/openapi.yaml via `npm run gen:types`). Never edit shapes here — change the
 * contract instead (ADR-0002). Web-only proposals live in `proposed.ts`.
 */
import type { components, paths } from './generated';

export type { components, paths };
type S = components['schemas'];

// ---- primitives ------------------------------------------------------------------------------
export type UUID = S['Uuid'];
export type ISODateTime = S['Timestamp'];
export type LocaleTag = S['LocaleTag'];
export type CountryCode = S['CountryCode'];
export type GeoPoint = S['GeoPoint'];
export type MediaRef = S['MediaRef'];
export type PageInfo = S['PageInfo'];
export type FieldError = S['FieldError'];
export type ContractErrorCode = S['ErrorCode'];
export type ContractProblem = S['Problem'];

// ---- identity & users ------------------------------------------------------------------------
export type ClientPlatform = S['ClientPlatform'];
export type LoginRequest = S['LoginRequest'];
export type RegisterRequest = S['RegisterRequest'];
export type RefreshRequest = S['RefreshRequest'];
export type LogoutRequest = S['LogoutRequest'];
export type SessionTokens = S['SessionTokens'];
export type AuthResult = S['AuthResult'];
export type DevIdpTokenRequest = S['DevIdpTokenRequest'];
export type DevIdpToken = S['DevIdpToken'];
export type RealtimeTicket = S['RealtimeTicket'];
export type Me = S['Me'];
export type MyAccount = S['MyAccount'];
export type MyProfile = S['MyProfile'];
export type Preferences = S['Preferences'];
export type PrivacySettings = S['PrivacySettings'];
export type UpdateMyProfileRequest = S['UpdateMyProfileRequest'];
export type UpdatePreferencesRequest = S['UpdatePreferencesRequest'];
export type UpdatePrivacySettingsRequest = S['UpdatePrivacySettingsRequest'];
export type PlatformRole = S['PlatformRole'];
export type PlatformPermission = S['PlatformPermission'];
export type AccountRestriction = S['AccountRestriction'];
export type ClientConfig = S['ClientConfig'];
export type TravelStyle = S['TravelStyle'];
export type LocationPrecision = S['LocationPrecision'];
export type PublicProfile = S['PublicProfile'];
export type UserSummary = S['UserSummary'];
export type BrowseDestination = S['BrowseDestination'];

// ---- billing ---------------------------------------------------------------------------------
export type Entitlements = S['Entitlements'];
export type QuotaStatus = S['QuotaStatus'];
export type FeatureKey = keyof Entitlements['features'];

// ---- destinations & guides -------------------------------------------------------------------
export type ContractDestinationSummary = S['DestinationSummary'];
export type ContractDestination = S['Destination'];
export type DestinationKind = S['DestinationKind'];
export type PlaceSummary = S['PlaceSummary'];
export type PlaceCategory = S['PlaceCategory'];
export type GuideSummary = S['GuideSummary'];
export type ContractGuide = S['Guide'];
export type ContentTier = S['ContentTier'];

// ---- social ----------------------------------------------------------------------------------
export type PostKind = S['PostKind'];
export type PostVisibility = S['PostVisibility'];
export type ReactionType = S['ReactionType'];
export type PostCounts = S['PostCounts'];
export type PostViewerState = S['PostViewerState'];
export type PostCore = S['PostCore'];
export type Post = S['Post'];
export type PublicPost = S['PublicPost'];
export type CreatePostRequest = S['CreatePostRequest'];
export type UpdatePostRequest = S['UpdatePostRequest'];
export type ReactionResult = S['ReactionResult'];
export type Comment = S['Comment'];
export type CreateCommentRequest = S['CreateCommentRequest'];
export type ShareLink = S['ShareLink'];
export type FeedTab = S['FeedTab'];
export type FeedSource = S['FeedSource'];
export type FeedContext = S['FeedContext'];
export type FeedPage = S['FeedPage'];

// ---- trust & safety --------------------------------------------------------------------------
export type ReportReason = S['ReportReason'];
export type ReportTargetType = S['ReportTargetType'];
export type CreateReportRequest = S['CreateReportRequest'];
export type ReportReceipt = S['ReportReceipt'];

/** Cursor-paginated envelope (doc 02 §5). */
export interface Page<T> {
  data: T[];
  page: PageInfo;
}

export interface CursorQuery {
  cursor?: string | null;
  limit?: number;
}
