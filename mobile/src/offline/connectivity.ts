import NetInfo, { useNetInfo, type NetInfoState } from '@react-native-community/netinfo';
import { onlineManager } from '@tanstack/react-query';

type ConnectivitySnapshot = Pick<NetInfoState, 'isConnected' | 'isInternetReachable'>;

/**
 * `null` means "not determined yet". It is treated as online so that the UI
 * does not flash an offline state at launch. Requests still fail fast and
 * surface `ApiNetworkError('offline')` if there is truly no network.
 */
export function isOnlineState(state: ConnectivitySnapshot): boolean {
  return state.isConnected !== false && state.isInternetReachable !== false;
}

export function useIsOnline(): boolean {
  return isOnlineState(useNetInfo());
}

/**
 * Lets TanStack Query pause and resume network requests with connectivity.
 * Call once at app start. Returns the unsubscribe function.
 */
export function bindQueryOnlineManager(): () => void {
  onlineManager.setEventListener((setOnline) =>
    NetInfo.addEventListener((state) => setOnline(isOnlineState(state))),
  );
  return () => onlineManager.setEventListener(() => undefined);
}
