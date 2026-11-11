import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { AdminOverview, AdminReport, AdminUser, AdminUserSummary } from '../api/types';
import { ConsoleRoutes } from '../App';
import { Layout } from '../components/Layout';
import { fakeApi, page, renderConsole } from '../test/render';

const OVERVIEW: AdminOverview = {
  generated_at: '2026-11-11T12:00:00Z',
  users: { total: 1280, new_7d: 42, new_30d: 160, active_7d: 615, suspended: 3 },
  premium_members: 97,
  posts_7d: 311,
  moderation: { open_reports: 5, unassigned_reports: 2, oldest_open_age_seconds: 7200, by_priority: { '80': 1 } },
  open_data_requests: 1,
  revenue_30d: [
    { currency: 'BRL', environment: 'sandbox', amount_minor: 149_00 },
    { currency: 'USD', environment: 'production', amount_minor: 4_99 },
  ],
};

const REPORT: AdminReport = {
  id: 'report-1',
  reporter: { id: 'u-rep', handle: 'lucas', display_name: 'Lucas' },
  target_type: 'post',
  target_id: 'post-1',
  target_author: { id: 'u-author', handle: 'spammer', display_name: 'Cheap Followers' },
  reason: 'spam',
  details: 'Selling followers',
  priority: 50,
  status: 'open',
  assigned_to: null,
  evidence: { body: 'Buy followers cheap!!!' },
  resolution_note: null,
  related_report_count: 2,
  created_at: '2026-11-11T10:00:00Z',
  resolved_at: null,
};

const SUMMARY: AdminUserSummary = {
  id: 'u-author',
  handle: 'spammer',
  display_name: 'Cheap Followers',
  status: 'active',
  roles: [],
  created_at: '2026-10-01T00:00:00Z',
  last_active_on: '2026-11-10',
};

const USER: AdminUser = {
  ...SUMMARY,
  email: 'cheap@example.com',
  open_report_count: 3,
  moderation_action_count: 0,
  suspended_until: null,
};

describe('navigation', () => {
  it('shows only the pages the role may open', () => {
    renderConsole(
      <Layout>
        <p>content</p>
      </Layout>,
      { role: 'moderator' },
    );
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Reports' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: 'Users' })).toBeInTheDocument();
    expect(within(nav).queryByRole('link', { name: 'Billing' })).toBeNull();
    expect(within(nav).queryByRole('link', { name: 'Staff' })).toBeNull();
    expect(within(nav).queryByRole('link', { name: 'Audit log' })).toBeNull();
  });

  it('asks for the work reason before showing any page', () => {
    renderConsole(
      <Layout>
        <p>secret content</p>
      </Layout>,
      { reason: null },
    );
    expect(screen.getByRole('heading', { name: 'What are you working on?' })).toBeInTheDocument();
    expect(screen.queryByText('secret content')).toBeNull();
  });

  it('keeps the work reason at 10 characters or more', async () => {
    const setReason = vi.fn();
    renderConsole(
      <Layout>
        <p>content</p>
      </Layout>,
      { reason: null, session: { setReason } },
    );
    const user = userEvent.setup();
    const start = screen.getByRole('button', { name: 'Start' });
    await user.type(screen.getByLabelText('Work reason'), 'short');
    expect(start).toBeDisabled();
    await user.type(screen.getByLabelText('Work reason'), ' but now long enough');
    await user.click(start);
    expect(setReason).toHaveBeenCalledWith('short but now long enough');
  });

  it('hides pages from roles without the permission', () => {
    renderConsole(<ConsoleRoutes />, { role: 'support', route: '/billing' });
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});

describe('overview', () => {
  it('shows real totals and revenue per currency, flagging test mode', async () => {
    const api = fakeApi({ overview: vi.fn(async () => OVERVIEW), ops: vi.fn(async () => ({ generated_at: 'x', moderation: {}, outbox: { unpublished_events: 0 }, jobs: { queued_due: 4 } })) });
    renderConsole(<ConsoleRoutes />, { api, route: '/' });
    expect(await screen.findByText('1,280')).toBeInTheDocument();
    expect(screen.getByText('+42 in the last 7 days')).toBeInTheDocument();
    expect(screen.getByText('2 unassigned')).toBeInTheDocument();
    expect(screen.getByText('R$149.00')).toBeInTheDocument();
    expect(screen.getByText('$4.99')).toBeInTheDocument();
    expect(screen.getAllByText('test mode')).toHaveLength(1);
  });

  it('leaves money out for roles without billing access', async () => {
    const api = fakeApi({ overview: vi.fn(async () => ({ ...OVERVIEW, revenue_30d: null, open_data_requests: null })) });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/' });
    expect(await screen.findByText('1,280')).toBeInTheDocument();
    expect(screen.queryByText('Revenue in the last 30 days')).toBeNull();
    expect(screen.queryByText('Open privacy requests')).toBeNull();
    expect(api.ops).not.toHaveBeenCalled();
  });

  it('speaks Portuguese', async () => {
    const api = fakeApi({ overview: vi.fn(async () => OVERVIEW), ops: vi.fn(async () => ({ generated_at: 'x', moderation: {}, outbox: {}, jobs: {} })) });
    renderConsole(<ConsoleRoutes />, { api, route: '/', locale: 'pt-BR' });
    expect(await screen.findByRole('heading', { name: 'Visão geral' })).toBeInTheDocument();
    expect(await screen.findByText(/R\$\s149,00/)).toBeInTheDocument();
  });
});

describe('reports', () => {
  it('lists the open queue and opens a report', async () => {
    const api = fakeApi({
      reports: vi.fn(async () => page([REPORT])),
      report: vi.fn(async () => REPORT),
      actions: vi.fn(async () => page([])),
    });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/reports' });
    const row = await screen.findByRole('row', { name: /Spam/ });
    expect(api.reports).toHaveBeenCalledWith(expect.objectContaining({ status: 'open' }), null);
    expect(within(row).getByText('+2')).toBeInTheDocument();
    await userEvent.setup().click(row);
    expect(await screen.findByRole('heading', { name: 'Spam · Post' })).toBeInTheDocument();
    expect(screen.getAllByText('Buy followers cheap!!!').length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: 'Open the account' })).toHaveAttribute('href', '/users/u-author');
  });

  it('resolves with an action on the author', async () => {
    const resolved = { ...REPORT, status: 'actioned' as const, resolution_note: 'Spam ring' };
    const api = fakeApi({
      report: vi.fn(async () => REPORT),
      actions: vi.fn(async () => page([])),
      resolveReport: vi.fn(async () => resolved),
    });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/reports/report-1' });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Resolve' }));
    const dialog = screen.getByRole('dialog', { name: 'Resolve the report' });
    // Moderators may not ban.
    expect(within(dialog).queryByRole('option', { name: 'Ban the author' })).toBeNull();
    await user.selectOptions(within(dialog).getByLabelText('Action'), 'suspend');
    await user.selectOptions(within(dialog).getByLabelText('For how long'), '7');
    await user.type(within(dialog).getByLabelText('Resolution note'), 'Spam ring');
    await user.click(within(dialog).getByRole('button', { name: 'Resolve' }));
    await waitFor(() => expect(api.resolveReport).toHaveBeenCalled());
    const [id, body] = vi.mocked(api.resolveReport).mock.calls[0]!;
    expect(id).toBe('report-1');
    expect(body).toMatchObject({
      status: 'actioned',
      resolution_note: 'Spam ring',
      action: { target_type: 'user', target_id: 'u-author', action: 'suspend', reason_code: 'spam', report_id: 'report-1' },
    });
    expect(body.action?.expires_at).toBeTruthy();
  });

  it('flags child safety reports', async () => {
    const api = fakeApi({ report: vi.fn(async () => ({ ...REPORT, reason: 'minor_safety' as const })), actions: vi.fn(async () => page([])) });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/reports/report-1' });
    expect(await screen.findByText(/Child safety report: handle it first/)).toBeInTheDocument();
  });
});

describe('users', () => {
  it('searches and shows the account with its actions', async () => {
    const api = fakeApi({
      users: vi.fn(async () => page([SUMMARY])),
      user: vi.fn(async () => USER),
      grants: vi.fn(async () => ({ data: [] })),
      transactions: vi.fn(async () =>
        page([
          {
            id: 'tx-1',
            user_id: 'u-author',
            provider: 'stripe',
            environment: 'sandbox',
            kind: 'payment',
            status: 'succeeded',
            amount_minor: 1190,
            currency: 'BRL',
            reason: 'purchase',
            provider_reference: 'pi_1',
            product: { id: 'p1', kind: 'non_renewing', period: 'P7D', title: '7-day pass' },
            occurred_at: '2026-11-11T11:00:00Z',
          },
        ]),
      ),
      actions: vi.fn(async () => page([])),
      dataRequests: vi.fn(async () => page([])),
    });
    renderConsole(<ConsoleRoutes />, { api, route: '/users' });
    const user = userEvent.setup();
    await user.type(screen.getByRole('searchbox'), 'cheap@example.com');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(api.users).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'cheap@example.com' }), null));
    await user.click(await screen.findByRole('row', { name: /Cheap Followers/ }));
    expect(await screen.findByText('cheap@example.com')).toBeInTheDocument();
    expect(await screen.findByText('R$11.90')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Suspend' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Give Premium' })).toBeInTheDocument();
    // Admins don't manage staff roles.
    expect(screen.queryByText('Staff roles')).toBeNull();
  });

  it('suspends for a number of days with notes', async () => {
    const api = fakeApi({
      user: vi.fn(async () => USER),
      actions: vi.fn(async () => page([])),
      suspend: vi.fn(async () => ({ ...USER, status: 'suspended' as const })),
    });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/users/u-author' });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Suspend' }));
    const dialog = screen.getByRole('dialog', { name: 'Suspend this account' });
    await user.selectOptions(within(dialog).getByLabelText('Reason'), 'scam');
    await user.type(within(dialog).getByLabelText('Notes (staff only)'), 'Phishing links in messages');
    await user.click(within(dialog).getByRole('button', { name: 'Suspend' }));
    await waitFor(() => expect(api.suspend).toHaveBeenCalled());
    const [id, body] = vi.mocked(api.suspend).mock.calls[0]!;
    expect(id).toBe('u-author');
    expect(body).toMatchObject({ reason_code: 'scam', notes: 'Phishing links in messages' });
    const days = (Date.parse(body.until!) - Date.now()) / 86_400_000;
    expect(Math.round(days)).toBe(7);
  });

  it('lets superadmins give and take staff roles', async () => {
    const api = fakeApi({
      user: vi.fn(async () => USER),
      grants: vi.fn(async () => ({ data: [] })),
      transactions: vi.fn(async () => page([])),
      actions: vi.fn(async () => page([])),
      dataRequests: vi.fn(async () => page([])),
      assignRole: vi.fn(async () => ({ ...USER, roles: ['moderator' as const] })),
    });
    renderConsole(<ConsoleRoutes />, { api, role: 'superadmin', route: '/users/u-author' });
    await userEvent.setup().click(await screen.findByRole('checkbox', { name: 'Moderator' }));
    await waitFor(() => expect(api.assignRole).toHaveBeenCalledWith('u-author', 'moderator'));
    expect(await screen.findByRole('checkbox', { name: 'Moderator' })).toBeChecked();
  });
});
