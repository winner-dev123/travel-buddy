import type { ApiClient } from '@/api';

/** Contract `NotificationType`. */
export type NotificationType =
  | 'connection_request'
  | 'connection_accepted'
  | 'new_message'
  | 'group_invitation'
  | 'group_announcement'
  | 'challenge_started'
  | 'challenge_result'
  | 'post_reaction'
  | 'post_comment'
  | 'new_follower'
  | 'follow_request'
  | 'moderation_notice'
  | 'subscription_notice'
  | 'ai_generation_ready'
  | 'data_export_ready';

export interface ChannelSettings {
  push?: boolean;
  in_app?: boolean;
  email?: boolean;
}

export interface QuietHours {
  start: string;
  end: string;
}

/** Contract `Preferences`. */
export interface Preferences {
  ui_locale: string;
  content_languages: string[];
  time_zone: string;
  currency_code: string;
  distance_unit: 'km' | 'mi';
  auto_translate: boolean;
  notification_settings: Partial<Record<NotificationType, ChannelSettings>>;
  quiet_hours?: QuietHours | null;
}

export type PreferencesChange = Partial<Omit<Preferences, 'notification_settings'>> & {
  notification_settings?: Partial<Record<NotificationType, ChannelSettings>>;
};

export const preferencesKey = ['me', 'preferences'] as const;

/** Notification types grouped the way people think about them. Account and safety notices
 * (moderation, subscription, data export) are always sent and not listed. */
export const NOTIFICATION_GROUPS = {
  messages: ['new_message'],
  people: ['connection_request', 'connection_accepted', 'new_follower', 'follow_request'],
  groups: ['group_invitation', 'group_announcement'],
  challenges: ['challenge_started', 'challenge_result'],
  stories: ['post_reaction', 'post_comment'],
  planning: ['ai_generation_ready'],
} as const satisfies Record<string, readonly NotificationType[]>;
export type NotificationGroup = keyof typeof NOTIFICATION_GROUPS;

/** Push is on for a group unless one of its types was turned off (the default is on). */
export function pushEnabled(preferences: Preferences, group: NotificationGroup): boolean {
  return NOTIFICATION_GROUPS[group].every(
    (type) => preferences.notification_settings[type]?.push !== false,
  );
}

export function fetchPreferences(client: ApiClient): Promise<Preferences> {
  return client.get<Preferences>('/v1/users/me/preferences');
}

/** `PATCH /v1/users/me/preferences`; notification settings are merged server-side. */
export function updatePreferences(
  client: ApiClient,
  changes: PreferencesChange,
): Promise<Preferences> {
  return client.patch<Preferences>('/v1/users/me/preferences', { body: changes });
}

/** The device's IANA time zone, if the runtime can tell. */
export function deviceTimeZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? null;
  } catch {
    return null;
  }
}
