// req: OFF-003
import { render, screen } from '@testing-library/react-native';

import { ApiNetworkError, ApiProblem } from '@/api/errors';
import { tokenStore } from '@/auth/tokenStore';
import { OnlineOnlyBadge } from '@/components/OnlineOnlyBadge';
import { i18n } from '@/i18n';
import { shouldRetry } from '@/query/queryClient';

import { isOnlineState } from '../connectivity';

beforeEach(async () => {
  await i18n.changeLanguage('en');
});

describe('isOnlineState', () => {
  it.each([
    [{ isConnected: true, isInternetReachable: true }, true],
    [{ isConnected: true, isInternetReachable: null }, true],
    [{ isConnected: null, isInternetReachable: null }, true],
    [{ isConnected: true, isInternetReachable: false }, false],
    [{ isConnected: false, isInternetReachable: null }, false],
  ])('%j → %s', (state, expected) => {
    expect(isOnlineState(state)).toBe(expected);
  });
});

describe('OnlineOnlyBadge', () => {
  it('labels online-only features with an accessible description', async () => {
    await render(<OnlineOnlyBadge online />);
    expect(screen.getByText('Online only')).toBeTruthy();
    expect(
      screen.getByLabelText('Online only. This feature needs an internet connection.'),
    ).toBeTruthy();
  });

  it('switches to the offline state', async () => {
    await render(<OnlineOnlyBadge online={false} />);
    expect(screen.getByText('Offline')).toBeTruthy();
    expect(
      screen.getByLabelText('You are offline. This feature is unavailable until you reconnect.'),
    ).toBeTruthy();
  });
});

describe('shouldRetry', () => {
  const problem = (status: number) =>
    new ApiProblem({ type: 'about:blank', title: 't', status, code: 'x' }, 'req');

  it('retries transient failures only, at most twice', () => {
    expect(shouldRetry(0, new ApiNetworkError('offline', 'req'))).toBe(true);
    expect(shouldRetry(0, new ApiNetworkError('timeout', 'req'))).toBe(true);
    expect(shouldRetry(0, new ApiNetworkError('aborted', 'req'))).toBe(false);
    expect(shouldRetry(0, problem(503))).toBe(true);
    expect(shouldRetry(0, problem(429))).toBe(true);
    expect(shouldRetry(0, problem(404))).toBe(false);
    expect(shouldRetry(0, problem(422))).toBe(false);
    expect(shouldRetry(2, problem(503))).toBe(false);
    expect(shouldRetry(0, new Error('bug'))).toBe(false);
  });
});

describe('tokenStore', () => {
  it('keeps the access token in memory and the refresh token in secure storage', async () => {
    tokenStore.setAccessToken('access');
    await tokenStore.setRefreshToken('refresh');

    expect(tokenStore.getAccessToken()).toBe('access');
    await expect(tokenStore.getRefreshToken()).resolves.toBe('refresh');

    await tokenStore.clear();
    expect(tokenStore.getAccessToken()).toBeNull();
    await expect(tokenStore.getRefreshToken()).resolves.toBeNull();
  });
});
