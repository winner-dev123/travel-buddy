import type { ApiClient } from '@/api';
import type { DestinationSummary, MediaRef, Page, UserSummary } from '@/features/feed/types';

export type GroupRole = 'owner' | 'admin' | 'moderator' | 'member';

/** Contract `Group` (the fields the app uses). */
export interface Group {
  id: string;
  name: string;
  description: string | null;
  cover: MediaRef | null;
  primary_destination: DestinationSummary;
  start_date: string | null;
  end_date: string | null;
  member_capacity: number;
  member_count: number;
  owner: UserSummary;
  status: 'active' | 'archived' | 'suspended';
  conversation_id: string;
  premium_features_active: boolean;
  my_membership: {
    role: GroupRole;
    status: 'active' | 'restricted' | 'removed' | 'left';
    permissions: string[];
    restricted_until: string | null;
  } | null;
  version: number;
  /** The pending ownership transfer I offered or was offered (null for everyone else). */
  pending_transfer?: OwnershipTransfer | null;
}

export interface GroupSummary {
  id: string;
  name: string;
  cover: MediaRef | null;
  primary_destination: DestinationSummary;
  member_count: number;
}

export interface GroupMember {
  group_id: string;
  user: UserSummary;
  role: GroupRole;
  status: 'active' | 'restricted' | 'removed' | 'left';
  joined_at: string;
  restricted_until: string | null;
}

export interface GroupInvitation {
  id: string;
  group: GroupSummary;
  kind: 'direct' | 'link';
  created_by: UserSummary | null;
  expires_at: string;
  status: string;
}

export interface CreatedInvitation {
  invitation: GroupInvitation;
  token: string | null;
  url: string | null;
}

export interface InvitationPreview {
  group: GroupSummary;
  inviter: UserSummary | null;
  expires_at: string;
  is_member: boolean;
}

export const groupKeys = {
  mine: ['groups', 'mine'] as const,
  invitations: ['groups', 'invitations'] as const,
  detail: (id: string) => ['groups', 'detail', id] as const,
  members: (id: string) => ['groups', 'members', id] as const,
  settings: (id: string) => ['groups', 'settings', id] as const,
};

/** Link invitations carry the token after `#t=`; people may paste the whole link or the code. */
export function tokenFrom(input: string): string {
  const trimmed = input.trim();
  const fragment = trimmed.match(/[#&]t=([A-Za-z0-9_-]+)/);
  return fragment?.[1] ?? trimmed;
}

export function listMyGroups(client: ApiClient): Promise<Page<Group>> {
  return client.get<Page<Group>>('/v1/groups', { query: { limit: 50 } });
}

export function listMyInvitations(client: ApiClient): Promise<Page<GroupInvitation>> {
  return client.get<Page<GroupInvitation>>('/v1/users/me/group-invitations', {
    query: { limit: 50 },
  });
}

export function getGroup(client: ApiClient, id: string): Promise<Group> {
  return client.get<Group>(`/v1/groups/${id}`);
}

export function listMembers(client: ApiClient, id: string): Promise<Page<GroupMember>> {
  return client.get<Page<GroupMember>>(`/v1/groups/${id}/members`, { query: { limit: 100 } });
}

export function createGroup(
  client: ApiClient,
  idempotencyKey: string,
  body: {
    name: string;
    primary_destination_id: string;
    member_capacity: number;
    description?: string;
  },
): Promise<Group> {
  return client.post<Group>('/v1/groups', { idempotencyKey, body });
}

export function respondToInvitation(
  client: ApiClient,
  id: string,
  accept: boolean,
): Promise<unknown> {
  return client.post(`/v1/group-invitations/${id}/${accept ? 'accept' : 'decline'}`);
}

export function previewInvitation(client: ApiClient, token: string): Promise<InvitationPreview> {
  return client.post<InvitationPreview>('/v1/group-invitations/preview', { body: { token } });
}

export function redeemInvitation(client: ApiClient, token: string): Promise<GroupMember> {
  return client.post<GroupMember>('/v1/group-invitations/redeem', { body: { token } });
}

export function createInviteLink(client: ApiClient, groupId: string): Promise<CreatedInvitation> {
  return client.post<CreatedInvitation>(`/v1/groups/${groupId}/invitations`, {
    body: { kind: 'link' },
  });
}

export function leaveGroup(client: ApiClient, groupId: string): Promise<void> {
  return client.post(`/v1/groups/${groupId}/leave`);
}

/** Contract `OwnershipTransfer`. */
export interface OwnershipTransfer {
  id: string;
  group_id: string;
  from_user: UserSummary;
  to_user: UserSummary;
  status: 'pending' | 'accepted' | 'declined' | 'cancelled' | 'expired';
  created_at: string;
  expires_at: string;
  responded_at: string | null;
}

/** Contract `GroupSettings`. */
export interface GroupSettings {
  members_can_invite: boolean;
  chat_mode: 'everyone' | 'admins_only';
  new_member_history: 'full' | 'from_join';
  version: number;
}

export type AssignableRole = 'admin' | 'moderator' | 'member';

/** Role ranks (docs/02 groups): nobody assigns a rank at or above their own. */
export const ROLE_RANK: Record<GroupRole, number> = {
  owner: 100,
  admin: 80,
  moderator: 50,
  member: 10,
};

export function getGroupSettings(client: ApiClient, groupId: string): Promise<GroupSettings> {
  return client.get<GroupSettings>(`/v1/groups/${groupId}/settings`);
}

export function updateGroupSettings(
  client: ApiClient,
  groupId: string,
  version: number,
  changes: Partial<Omit<GroupSettings, 'version'>>,
): Promise<GroupSettings> {
  return client.patch<GroupSettings>(`/v1/groups/${groupId}/settings`, {
    body: changes,
    ifMatchVersion: version,
  });
}

export function changeMemberRole(
  client: ApiClient,
  groupId: string,
  userId: string,
  role: AssignableRole,
): Promise<GroupMember> {
  return client.patch<GroupMember>(`/v1/groups/${groupId}/members/${userId}`, { body: { role } });
}

export function removeMember(client: ApiClient, groupId: string, userId: string): Promise<void> {
  return client.delete(`/v1/groups/${groupId}/members/${userId}`);
}

export function offerTransfer(
  client: ApiClient,
  groupId: string,
  toUserId: string,
): Promise<OwnershipTransfer> {
  return client.post<OwnershipTransfer>(`/v1/groups/${groupId}/ownership-transfers`, {
    body: { to_user_id: toUserId },
  });
}

export function answerTransfer(
  client: ApiClient,
  groupId: string,
  transferId: string,
  action: 'accept' | 'decline' | 'cancel',
): Promise<OwnershipTransfer> {
  return client.post<OwnershipTransfer>(
    `/v1/groups/${groupId}/ownership-transfers/${transferId}/${action}`,
  );
}
