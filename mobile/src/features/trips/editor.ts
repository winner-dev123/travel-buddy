import { randomUUID } from 'expo-crypto';
import { Directory, File, Paths } from 'expo-file-system';

import type { ApiClient } from '@/api';
import type { Trip, TripItem } from '@/features/explore/api';

/** Contract `ItineraryItemKind`. */
export const ITEM_KINDS = ['activity', 'meal', 'transit', 'lodging', 'note', 'free_time'] as const;
export type ItemKind = (typeof ITEM_KINDS)[number];

export interface ItemFields {
  kind?: ItemKind;
  title?: string;
  notes?: string | null;
  start_time?: string | null;
  duration_minutes?: number | null;
  day_id?: string;
  /** `null`: first in the day; left out: at the end (contract `ItineraryItemPatch`). */
  after_item_id?: string | null;
}

/** One manual change, kept on the device until the server has it (TRIP-004). */
export interface PendingEdit {
  op_id: string;
  entity: 'item';
  action: 'create' | 'update' | 'delete';
  entity_id: string;
  parent_id: string | null;
  fields: ItemFields;
  client_updated_at: string;
}

export interface SyncOutcome {
  trip: Trip;
  conflicts: number;
}

export function newEdit(
  action: PendingEdit['action'],
  itemId: string | null,
  fields: ItemFields,
  parentId: string | null = null,
): PendingEdit {
  return {
    op_id: randomUUID(),
    entity: 'item',
    action,
    entity_id: itemId ?? randomUUID(),
    parent_id: parentId,
    fields,
    client_updated_at: new Date().toISOString(),
  };
}

function place(items: TripItem[], item: TripItem, after: string | null | undefined): TripItem[] {
  const rest = items.filter((other) => other.id !== item.id);
  if (after === undefined) return [...rest, item];
  if (after === null) return [item, ...rest];
  const index = rest.findIndex((other) => other.id === after);
  return index < 0
    ? [...rest, item]
    : [...rest.slice(0, index + 1), item, ...rest.slice(index + 1)];
}

/** The trip as this device shows it: the server's version with the pending edits on top. */
export function applyEdits(trip: Trip, edits: readonly PendingEdit[]): Trip {
  const days = trip.days.map((day) => ({ ...day, items: [...day.items] }));
  for (const edit of edits) {
    const from = days.find((day) => day.items.some((item) => item.id === edit.entity_id));
    const current = from?.items.find((item) => item.id === edit.entity_id);
    if (edit.action === 'delete') {
      if (from) from.items = from.items.filter((item) => item.id !== edit.entity_id);
      continue;
    }
    if (edit.action === 'create' && !current) {
      const day = days.find((d) => d.id === edit.parent_id);
      if (!day) continue;
      const created: TripItem = {
        id: edit.entity_id,
        kind: edit.fields.kind ?? 'activity',
        title: edit.fields.title ?? '',
        notes: edit.fields.notes ?? null,
        start_time: edit.fields.start_time ?? null,
        duration_minutes: edit.fields.duration_minutes ?? null,
        origin: 'user',
        unverified: false,
        place: null,
      };
      day.items = place(day.items, created, edit.fields.after_item_id);
      continue;
    }
    if (!from || !current) continue; // deleted on the server meanwhile
    const { day_id: dayId, after_item_id: after, ...changes } = edit.fields;
    const updated: TripItem = { ...current, ...changes } as TripItem;
    const target = days.find((day) => day.id === (dayId ?? from.id)) ?? from;
    if (target !== from || 'after_item_id' in edit.fields) {
      from.items = from.items.filter((item) => item.id !== current.id);
      target.items = place(target.items, updated, after);
    } else {
      from.items = from.items.map((item) => (item.id === current.id ? updated : item));
    }
  }
  return { ...trip, days };
}

function toOperation(edit: PendingEdit) {
  const base = {
    op_id: edit.op_id,
    entity: edit.entity,
    action: edit.action,
    entity_id: edit.entity_id,
    client_updated_at: edit.client_updated_at,
  };
  if (edit.action === 'delete') return base;
  if (edit.action === 'create') {
    // `ItineraryItemInput` takes no nulls: leave unset fields out.
    const fields = Object.fromEntries(
      Object.entries(edit.fields).filter(
        ([key, value]) => key !== 'day_id' && (value !== null || key === 'after_item_id'),
      ),
    );
    return { ...base, parent_id: edit.parent_id, fields };
  }
  return { ...base, fields: edit.fields };
}

interface SyncResponse {
  trip: Trip;
  applied_op_ids: string[];
  conflicts: { op_id: string }[];
}

/** `POST /v1/trips/{id}/sync`: newer writes win; edits the server made since `base_version`
 * and later than ours come back as conflicts with the server's state (TRIP-004). */
export async function syncEdits(
  client: ApiClient,
  trip: Trip,
  edits: readonly PendingEdit[],
): Promise<SyncOutcome> {
  const result = await client.post<SyncResponse>(`/v1/trips/${trip.id}/sync`, {
    body: { base_version: trip.version, operations: edits.map(toOperation) },
    idempotencyKey: client.newIdempotencyKey(),
  });
  return { trip: result.trip, conflicts: result.conflicts.length };
}

const folder = () => new Directory(Paths.document, 'trip-edits');
const editsFile = (tripId: string) => new File(folder(), `${tripId}.json`);

/** Pending edits survive restarts and airplane mode. */
export async function loadEdits(tripId: string): Promise<PendingEdit[]> {
  const file = editsFile(tripId);
  if (!file.exists) return [];
  try {
    return JSON.parse(await file.text()) as PendingEdit[];
  } catch {
    return [];
  }
}

export async function saveEdits(tripId: string, edits: readonly PendingEdit[]): Promise<void> {
  const file = editsFile(tripId);
  if (edits.length === 0) {
    if (file.exists) file.delete();
    return;
  }
  folder().create({ intermediates: true, idempotent: true });
  await file.write(JSON.stringify(edits));
}
