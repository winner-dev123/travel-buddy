import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useState } from 'react';

import { ApiNetworkError, getApiClient } from '@/api';
import { exploreKeys, type Trip } from '@/features/explore/api';
import {
  applyEdits,
  loadEdits,
  type PendingEdit,
  saveEdits,
  syncEdits,
} from '@/features/trips/editor';
import { useIsOnline } from '@/offline/connectivity';

export type EditorStatus = 'saved' | 'saving' | 'offline' | 'failed';

export interface TripEditor {
  /** The trip with this device's pending edits applied. */
  view: Trip | undefined;
  status: EditorStatus;
  pending: number;
  conflicts: number;
  edit: (change: PendingEdit) => void;
  discard: () => void;
  dismissConflicts: () => void;
}

/** Offline-first itinerary editing (TRIP-004): every change is shown at once, kept on the
 * device, and sent in batches whenever the device is online. */
export function useTripEditor(trip: Trip | undefined): TripEditor {
  const queryClient = useQueryClient();
  const online = useIsOnline();
  const tripId = trip?.id;
  const [edits, setEdits] = useState<PendingEdit[]>([]);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState(0);
  // The batch (and connectivity) that last failed: retried only after a new edit or reconnect,
  // never in a loop.
  const [failedKey, setFailedKey] = useState<string | null>(null);
  // Counts reconnections, so a batch that failed is tried again once the device is back online.
  const [seenOnline, setSeenOnline] = useState(online);
  const [connection, setConnection] = useState(0);
  if (online !== seenOnline) {
    setSeenOnline(online);
    if (online) setConnection((count) => count + 1);
  }

  useEffect(() => {
    if (!tripId) return;
    let active = true;
    void loadEdits(tripId).then((stored) => {
      if (!active) return;
      setEdits(stored);
      setLoadedFor(tripId);
    });
    return () => {
      active = false;
    };
  }, [tripId]);

  const sync = useMutation({
    mutationFn: ({ base, batch }: { base: Trip; batch: PendingEdit[]; key: string }) =>
      syncEdits(getApiClient(), base, batch),
    onError: (_error, { key }) => setFailedKey(key),
    onSuccess: (outcome, { batch }) => {
      setFailedKey(null);
      // The server answered for the whole batch with its own state: every sent edit is done here,
      // applied or not, so nothing is ever sent again in a loop.
      const sent = new Set(batch.map((change) => change.op_id));
      queryClient.setQueryData(exploreKeys.trip(outcome.trip.id), outcome.trip);
      void queryClient.invalidateQueries({ queryKey: exploreKeys.trips, exact: true }); // the list only
      setEdits((current) => {
        const rest = current.filter((edit) => !sent.has(edit.op_id));
        void saveEdits(outcome.trip.id, rest);
        return rest;
      });
      if (outcome.conflicts) setConflicts((count) => count + outcome.conflicts);
    },
  });

  const ready = trip !== undefined && loadedFor === trip.id;
  const batchKey = `${connection}:${edits.map((change) => change.op_id).join(',')}`;
  const { isPending, mutate } = sync;
  useEffect(() => {
    if (ready && online && edits.length > 0 && !isPending && trip && batchKey !== failedKey) {
      mutate({ base: trip, batch: edits, key: batchKey });
    }
  }, [ready, online, edits, isPending, trip, mutate, batchKey, failedKey]);

  const edit = useCallback(
    (change: PendingEdit) => {
      if (!tripId) return;
      setEdits((current) => {
        const next = [...current, change];
        void saveEdits(tripId, next);
        return next;
      });
    },
    [tripId],
  );

  const discard = useCallback(() => {
    if (!tripId) return;
    setEdits([]);
    setFailedKey(null);
    sync.reset();
    void saveEdits(tripId, []);
  }, [tripId, sync]);

  const networkFailure = sync.error instanceof ApiNetworkError;
  let status: EditorStatus = 'saved';
  if (edits.length > 0) {
    if (sync.isPending) status = 'saving';
    else if (!online || networkFailure) status = 'offline';
    else if (sync.isError) status = 'failed';
    else status = 'saving';
  }

  return {
    view: trip ? applyEdits(trip, edits) : undefined,
    status,
    pending: edits.length,
    conflicts,
    edit,
    discard,
    dismissConflicts: () => setConflicts(0),
  };
}
