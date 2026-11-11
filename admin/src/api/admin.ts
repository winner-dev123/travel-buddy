import { newIdempotencyKey, type Query, type RequestOptions } from './http';
import type {
  AdminDataRequest,
  AdminOverview,
  AdminProduct,
  AdminReport,
  AdminTransaction,
  AdminUser,
  AdminUserSummary,
  AuditLogEntry,
  EntitlementGrant,
  Me,
  MessageFilterPolicy,
  ModerationAction,
  ModerationActionRequest,
  OpsSummary,
  Page,
  PlatformRole,
  ReportStatus,
  Uuid,
} from './types';

/** An authenticated JSON call (the session adds the token and the audit justification). */
export type Requester = <T>(path: string, options?: RequestOptions) => Promise<T>;

export interface ReportFilters {
  status?: ReportStatus;
  reason?: string;
  target_type?: string;
  assigned_to?: string;
}

export interface ResolveReportBody {
  status: 'actioned' | 'dismissed';
  resolution_note: string;
  action?: ModerationActionRequest;
}

export interface UserSearch {
  q?: string;
  status?: string;
  staff?: boolean;
}

export function createAdminApi(request: Requester) {
  const page = <T>(path: string, query: Query, cursor?: string | null) =>
    request<Page<T>>(path, { query: { ...query, cursor: cursor ?? undefined, limit: 25 } });

  return {
    me: () => request<Me>('/v1/users/me'),

    overview: () => request<AdminOverview>('/v1/admin/metrics/overview'),
    ops: () => request<OpsSummary>('/v1/admin/ops/summary'),

    reports: (filters: ReportFilters, cursor?: string | null) =>
      page<AdminReport>('/v1/admin/reports', { ...filters }, cursor),
    report: (id: Uuid) => request<AdminReport>(`/v1/admin/reports/${id}`),
    assignReport: (id: Uuid, assigneeId: Uuid) =>
      request<AdminReport>(`/v1/admin/reports/${id}/assign`, {
        method: 'POST',
        body: { assignee_id: assigneeId },
      }),
    resolveReport: (id: Uuid, body: ResolveReportBody) =>
      request<AdminReport>(`/v1/admin/reports/${id}/resolve`, { method: 'POST', body }),

    actions: (targetType: string, targetId: Uuid, cursor?: string | null) =>
      page<ModerationAction>(
        '/v1/admin/moderation-actions',
        { target_type: targetType, target_id: targetId },
        cursor,
      ),
    createAction: (body: ModerationActionRequest) =>
      request<ModerationAction>('/v1/admin/moderation-actions', {
        method: 'POST',
        body,
        headers: { 'Idempotency-Key': newIdempotencyKey() },
      }),

    users: (search: UserSearch, cursor?: string | null) =>
      page<AdminUserSummary>('/v1/admin/users', { ...search }, cursor),
    user: (id: Uuid) => request<AdminUser>(`/v1/admin/users/${id}`),
    suspend: (id: Uuid, body: { reason_code: string; notes: string; until: string | null }) =>
      request<AdminUser>(`/v1/admin/users/${id}/suspend`, { method: 'POST', body }),
    reinstate: (id: Uuid, notes: string) =>
      request<AdminUser>(`/v1/admin/users/${id}/reinstate`, { method: 'POST', body: { notes } }),
    grants: (id: Uuid) =>
      request<{ data: EntitlementGrant[] }>(`/v1/admin/users/${id}/entitlement-grants`),
    grant: (id: Uuid, body: { entitlement_key: string; ends_at: string; reason: string }) =>
      request<EntitlementGrant>(`/v1/admin/users/${id}/entitlement-grants`, {
        method: 'POST',
        body,
      }),
    revokeGrant: (grantId: Uuid) =>
      request<EntitlementGrant>(`/v1/admin/entitlement-grants/${grantId}/revoke`, {
        method: 'POST',
      }),
    assignRole: (id: Uuid, role: PlatformRole) =>
      request<AdminUser>(`/v1/admin/users/${id}/roles/${role}`, { method: 'PUT' }),
    removeRole: (id: Uuid, role: PlatformRole) =>
      request<AdminUser>(`/v1/admin/users/${id}/roles/${role}`, { method: 'DELETE' }),

    transactions: (filters: { user_id?: Uuid; status?: string }, cursor?: string | null) =>
      page<AdminTransaction>('/v1/admin/billing/transactions', { ...filters }, cursor),
    products: () => request<{ data: AdminProduct[] }>('/v1/admin/products'),
    updateProduct: (id: Uuid, body: { active?: boolean; sort_order?: number }) =>
      request<AdminProduct>(`/v1/admin/products/${id}`, { method: 'PATCH', body }),

    dataRequests: (
      filters: { state?: string; kind?: string; user_id?: Uuid },
      cursor?: string | null,
    ) => page<AdminDataRequest>('/v1/admin/data-requests', { ...filters }, cursor),
    resolveDataRequest: (id: Uuid, body: { status: 'completed' | 'rejected'; resolution: string }) =>
      request<AdminDataRequest>(`/v1/admin/data-requests/${id}/resolve`, {
        method: 'POST',
        body,
      }),

    auditLogs: (
      filters: { resource_type?: string; resource_id?: string; actor_id?: string },
      cursor?: string | null,
    ) => page<AuditLogEntry>('/v1/admin/audit-logs', { ...filters }, cursor),

    messageFilter: () => request<MessageFilterPolicy>('/v1/admin/safety/message-filter'),
    updateMessageFilter: (body: { terms: string[]; new_connection_days: number; version: number }) =>
      request<MessageFilterPolicy>('/v1/admin/safety/message-filter', { method: 'PUT', body }),
  };
}

export type AdminApi = ReturnType<typeof createAdminApi>;
