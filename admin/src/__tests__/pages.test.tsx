import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api/http';
import type {
  AdminOverview,
  AdminProvider,
  AdminProviderDocument,
  AdminProviderSummary,
  AdminReport,
  AdminUser,
  AdminUserSummary,
} from '../api/types';
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

const OWNER = { id: 'u-owner', handle: 'marina', display_name: 'Marina Costa' };

const PROVIDER_SUMMARY: AdminProviderSummary = {
  id: 'prov-1',
  kind: 'guide',
  status: 'submitted',
  display_name: 'Rio Walks',
  country_code: 'BR',
  owner: OWNER,
  submitted_at: '2026-11-14T09:00:00Z',
  decided_at: null,
  created_at: '2026-11-10T09:00:00Z',
};

const ID_DOCUMENT: AdminProviderDocument = {
  id: 'doc-1',
  kind: 'identity',
  number: 'RG 12.345.678-9',
  issuing_country: 'BR',
  expires_on: '2030-05-31',
  status: 'pending',
  file_available: true,
  created_at: '2026-11-12T09:00:00Z',
  decided_at: null,
  decided_by: null,
  uploaded_by: 'u-owner',
};

const REGISTRY_DOCUMENT: AdminProviderDocument = {
  ...ID_DOCUMENT,
  id: 'doc-2',
  kind: 'tourism_registry',
  number: 'CAD-0001',
  expires_on: '2025-01-31',
  file_available: false,
};

const APPLICATION: AdminProvider = {
  provider: {
    id: 'prov-1',
    slug: 'rio-walks',
    kind: 'guide',
    status: 'submitted',
    display_name: 'Rio Walks',
    tagline: 'Hidden corners of Rio, on foot',
    logo: null,
    cover: null,
    base_destination: {
      id: 'd-rio',
      kind: 'city',
      slug: 'rio-de-janeiro-br',
      path: 'brazil/rio-de-janeiro',
      name: 'Rio de Janeiro',
      country_code: 'BR',
      country_name: 'Brazil',
      region_name: 'Rio de Janeiro',
    },
    languages: ['pt-BR', 'en'],
    specialties: ['city_tours', 'history_culture'],
    rating_average: null,
    rating_count: 0,
    verified_at: null,
    response_time_seconds: null,
    about: 'Licensed guide since 2015.',
    years_experience: 9,
    website_url: 'javascript:alert(1)',
    service_areas: [],
    published_offering_count: 0,
    country_code: 'BR',
    legal_name: 'Marina Costa da Silva',
    registration_number: '27.123456.10.0001-5',
    review_note: null,
    suspended_reason: null,
    submitted_at: '2026-11-14T09:00:00Z',
    decided_at: null,
    locked_fields: [],
    terms_version: '2026-11-01',
    terms_accepted_version: '2026-11-01',
    missing_for_submit: [],
    inquiry_count: 0,
    response_count: 0,
    version: 3,
    created_at: '2026-11-10T09:00:00Z',
  },
  owner: OWNER,
  members: [
    { user: OWNER, role: 'owner', status: 'active', created_at: '2026-11-10T09:00:00Z', accepted_at: '2026-11-10T09:00:00Z' },
  ],
  documents: [ID_DOCUMENT, REGISTRY_DOCUMENT],
  decided_by: null,
  open_report_count: 0,
};

function withStatus(status: AdminProvider['provider']['status'], extra: Partial<AdminProvider['provider']> = {}): AdminProvider {
  return { ...APPLICATION, provider: { ...APPLICATION.provider, status, ...extra } };
}

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

  it('labels reports about guides and companies and links to the application', async () => {
    const aboutReview: AdminReport = {
      ...REPORT,
      id: 'report-2',
      target_type: 'provider_review',
      target_id: 'review-1',
      reason: 'scam',
      evidence: { provider_id: 'prov-1', review_id: 'review-1', rating: 1, body: 'Pay me by Pix first' },
    };
    const api = fakeApi({
      reports: vi.fn(async () => page([aboutReview])),
      report: vi.fn(async () => aboutReview),
      actions: vi.fn(async () => page([])),
    });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/reports' });
    expect(screen.getByRole('option', { name: 'Guide or company' })).toBeInTheDocument();
    const row = await screen.findByRole('row', { name: /Scam/ });
    expect(within(row).getByText('Review')).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(row);
    expect(await screen.findByRole('heading', { name: 'Scam · Review' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open the guide or company' })).toHaveAttribute('href', '/providers/prov-1');
    // A review can be removed, not limited.
    await user.click(screen.getByRole('button', { name: 'Resolve' }));
    const dialog = screen.getByRole('dialog', { name: 'Resolve the report' });
    expect(within(dialog).getByRole('option', { name: 'Remove the content' })).toBeInTheDocument();
    expect(within(dialog).queryByRole('option', { name: 'Limit who sees it' })).toBeNull();
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

describe('providers', () => {
  it('is in the menu and open only to staff who verify providers', () => {
    const { unmount } = renderConsole(
      <Layout>
        <p>content</p>
      </Layout>,
      { role: 'moderator' },
    );
    const nav = screen.getByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Guides and companies' })).toHaveAttribute('href', '/providers');
    unmount();
    renderConsole(<ConsoleRoutes />, { role: 'support', route: '/providers' });
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });

  it('lists the review queue, filters it and opens an application', async () => {
    const api = fakeApi({
      providers: vi.fn(async () => page([PROVIDER_SUMMARY])),
      provider: vi.fn(async () => APPLICATION),
    });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/providers' });
    const row = await screen.findByRole('row', { name: /Rio Walks/ });
    expect(api.providers).toHaveBeenCalledWith({ status: 'submitted', kind: undefined }, null);
    expect(within(row).getByText('Guide')).toBeInTheDocument();
    expect(within(row).getByText('Brazil')).toBeInTheDocument();
    expect(within(row).getByText('Marina Costa')).toBeInTheDocument();
    expect(within(row).getByText('Waiting for review')).toBeInTheDocument();

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText('Type'), 'company');
    await waitFor(() =>
      expect(api.providers).toHaveBeenLastCalledWith({ status: 'submitted', kind: 'company' }, null),
    );
    await user.selectOptions(screen.getByLabelText('Status'), 'approved');
    await waitFor(() =>
      expect(api.providers).toHaveBeenLastCalledWith({ status: 'approved', kind: 'company' }, null),
    );

    await user.click(await screen.findByRole('row', { name: /Rio Walks/ }));
    expect(await screen.findByRole('heading', { name: 'Rio Walks' })).toBeInTheDocument();
    expect(api.provider).toHaveBeenCalledWith('prov-1');
  });

  it('shows the private details next to the public profile, and the documents', async () => {
    const api = fakeApi({ provider: vi.fn(async () => APPLICATION) });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/providers/prov-1' });
    expect(await screen.findByRole('heading', { name: 'Rio Walks' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Checked by staff (private)' })).toBeInTheDocument();
    expect(screen.getByText('Marina Costa da Silva')).toBeInTheDocument();
    expect(screen.getByText('27.123456.10.0001-5')).toBeInTheDocument();
    expect(screen.getByText('Brazil (BR)')).toBeInTheDocument();
    expect(screen.getByText('Hidden corners of Rio, on foot')).toBeInTheDocument();
    expect(screen.getByText('Rio de Janeiro, Rio de Janeiro, Brazil')).toBeInTheDocument();
    expect(screen.getByText('City tours, History and culture')).toBeInTheDocument();
    expect(screen.getByText(/English/)).toBeInTheDocument();
    // An applicant's website never becomes a script link.
    expect(screen.getByText('javascript:alert(1)').closest('a')).toBeNull();

    const idRow = screen.getByRole('row', { name: /Identity document/ });
    expect(within(idRow).getByText('RG 12.345.678-9')).toBeInTheDocument();
    expect(within(idRow).getByText('Pending')).toBeInTheDocument();
    expect(within(idRow).getByText('Kept')).toBeInTheDocument();
    expect(within(idRow).getByRole('button', { name: /Open/ })).toBeEnabled();
    const registryRow = screen.getByRole('row', { name: /Tourism registry/ });
    expect(within(registryRow).getByText('Deleted')).toBeInTheDocument();
    expect(within(registryRow).getByText('Expired')).toBeInTheDocument();
    expect(within(registryRow).queryByRole('button', { name: /Open/ })).toBeNull();

    // A submitted application gets a decision, not a suspension.
    expect(screen.getByRole('heading', { name: 'Decision' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Suspend' })).toBeNull();
  });

  it('blocks asking for changes without a note, then sends the note', async () => {
    const updated = withStatus('changes_requested', { review_note: 'Send a sharper photo of your ID.' });
    const api = fakeApi({
      provider: vi.fn(async () => APPLICATION),
      decideProvider: vi.fn(async () => updated),
    });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/providers/prov-1' });
    const user = userEvent.setup();
    await user.click(await screen.findByRole('radio', { name: /Ask for changes/ }));
    await user.click(screen.getByRole('button', { name: 'Ask for changes' }));
    expect(await screen.findByText('Tell the applicant what to change, or why it is rejected.')).toBeInTheDocument();
    expect(screen.getByLabelText('Note to the applicant')).toHaveFocus();
    expect(api.decideProvider).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText('Note to the applicant'), '  Send a sharper photo of your ID. ');
    await user.click(screen.getByRole('button', { name: 'Ask for changes' }));
    await waitFor(() => expect(api.decideProvider).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.decideProvider).mock.calls[0]).toEqual([
      'prov-1',
      { decision: 'request_changes', note: 'Send a sharper photo of your ID.' },
    ]);
    // The page shows the answer at once; the decision form is gone.
    expect(await screen.findByText('Changes requested')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Decision' })).toBeNull();
  });

  it('approves with a decision for each document', async () => {
    const approved = withStatus('approved', { verified_at: '2026-11-16T12:00:00Z' });
    const api = fakeApi({
      provider: vi.fn(async () => APPLICATION),
      decideProvider: vi.fn(async () => approved),
    });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/providers/prov-1' });
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText('Identity document · RG 12.345.678-9'), 'accepted');
    await user.selectOptions(screen.getByLabelText('Tourism registry (e.g. CADASTUR) · CAD-0001'), 'rejected');
    await user.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(api.decideProvider).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.decideProvider).mock.calls[0]).toEqual([
      'prov-1',
      {
        decision: 'approve',
        documents: [
          { id: 'doc-1', status: 'accepted' },
          { id: 'doc-2', status: 'rejected' },
        ],
      },
    ]);
    expect(await screen.findByRole('button', { name: 'Suspend' })).toBeInTheDocument();
    // Refreshed from the answer, without another audited read.
    expect(api.provider).toHaveBeenCalledTimes(1);
  });

  it('opens a document in a new tab and explains a deleted file', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    const providerDocumentFile = vi
      .fn()
      .mockResolvedValueOnce({ url: 'https://files.test/doc-1?sig=abc', expires_at: '2026-11-16T12:05:00Z' })
      .mockRejectedValueOnce(new ApiError({ status: 410, code: 'conflict', detail: 'The file is no longer kept.' }));
    const api = fakeApi({ provider: vi.fn(async () => APPLICATION), providerDocumentFile });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/providers/prov-1' });
    const user = userEvent.setup();
    const openButton = () =>
      within(screen.getByRole('row', { name: /Identity document/ })).queryByRole('button', { name: /Open/ });

    await user.click((await screen.findByRole('button', { name: /Open: Identity document/ })));
    await waitFor(() =>
      expect(open).toHaveBeenCalledWith('https://files.test/doc-1?sig=abc', '_blank', expect.stringContaining('noopener')),
    );
    expect(providerDocumentFile).toHaveBeenCalledWith('prov-1', 'doc-1');
    await waitFor(() => expect(openButton()).toBeEnabled());

    await user.click(openButton()!);
    expect(await screen.findByText(/deleted after the 90-day retention/)).toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /Identity document/ })).getByText('Deleted')).toBeInTheDocument();
    expect(openButton()).toBeNull();
    expect(open).toHaveBeenCalledTimes(1);
  });

  it('says when a document is still processing', async () => {
    const api = fakeApi({
      provider: vi.fn(async () => APPLICATION),
      providerDocumentFile: vi.fn(async () => {
        throw new ApiError({ status: 409, code: 'conflict', detail: 'The file is still being processed.' });
      }),
    });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/providers/prov-1' });
    await userEvent.setup().click(await screen.findByRole('button', { name: /Open: Identity document/ }));
    expect(await screen.findByText(/still being processed. Try again in a minute/)).toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /Identity document/ })).getByText('Kept')).toBeInTheDocument();
  });

  it('suspends an approved provider with a reason, then reinstates it', async () => {
    const approved = withStatus('approved', { verified_at: '2026-11-16T12:00:00Z' });
    const suspended = withStatus('suspended', {
      verified_at: '2026-11-16T12:00:00Z',
      suspended_reason: 'Asked travelers for card numbers',
    });
    const api = fakeApi({
      provider: vi.fn(async () => approved),
      suspendProvider: vi.fn(async () => suspended),
      reinstateProvider: vi.fn(async () => approved),
    });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/providers/prov-1' });
    const user = userEvent.setup();
    expect(await screen.findByText(/Verified since/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Decision' })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Suspend' }));
    const dialog = screen.getByRole('dialog', { name: 'Suspend this guide or company' });
    const submit = within(dialog).getByRole('button', { name: 'Suspend' });
    expect(submit).toBeDisabled();
    await user.type(within(dialog).getByLabelText('Reason (their team sees it)'), 'Asked travelers for card numbers');
    await user.click(submit);
    await waitFor(() =>
      expect(api.suspendProvider).toHaveBeenCalledWith('prov-1', 'Asked travelers for card numbers'),
    );
    expect(await screen.findByText('Asked travelers for card numbers')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Reinstate' }));
    await user.click(
      within(screen.getByRole('dialog', { name: 'Reinstate this guide or company' })).getByRole('button', {
        name: 'Reinstate',
      }),
    );
    await waitFor(() => expect(api.reinstateProvider).toHaveBeenCalledWith('prov-1'));
    expect(await screen.findByRole('button', { name: 'Suspend' })).toBeInTheDocument();
  });

  it('speaks Portuguese', async () => {
    const api = fakeApi({ providers: vi.fn(async () => page([PROVIDER_SUMMARY])) });
    renderConsole(<ConsoleRoutes />, { api, role: 'moderator', route: '/providers', locale: 'pt-BR' });
    expect(screen.getByRole('heading', { name: 'Guias e empresas' })).toBeInTheDocument();
    const row = await screen.findByRole('row', { name: /Rio Walks/ });
    expect(within(row).getByText('Aguardando análise')).toBeInTheDocument();
    expect(within(row).getByText('Brasil')).toBeInTheDocument();
  });
});
