import { Directory, File, Paths } from 'expo-file-system';
import { create } from 'zustand';

/**
 * How chats look on this device (SCR-119 Chat settings): which side the send button sits on
 * (left for left-handed use) and the background. A background is either one of the built-in trip
 * photos or a photo from the traveller's own stories, copied into the app's documents so chats
 * show it without a network.
 */
export type SendSide = 'right' | 'left';

export type ChatBackground =
  | { kind: 'none' }
  | { kind: 'builtin'; id: BuiltinBackgroundId }
  | { kind: 'photo'; uri: string; mediaId: string };

export const BUILTIN_BACKGROUNDS = {
  coast: require('../../assets/chat-backgrounds/coast.jpg') as number,
  mountains: require('../../assets/chat-backgrounds/mountains.jpg') as number,
} as const;
export type BuiltinBackgroundId = keyof typeof BUILTIN_BACKGROUNDS;
export const BUILTIN_BACKGROUND_IDS = Object.keys(BUILTIN_BACKGROUNDS) as BuiltinBackgroundId[];

export interface ChatPreferences {
  sendSide: SendSide;
  background: ChatBackground;
}

export const DEFAULT_CHAT_PREFERENCES: ChatPreferences = {
  sendSide: 'right',
  background: { kind: 'none' },
};

interface ChatPreferencesState extends ChatPreferences {
  set: (preferences: ChatPreferences) => void;
}

export const useChatPreferences = create<ChatPreferencesState>()((set) => ({
  ...DEFAULT_CHAT_PREFERENCES,
  set: (preferences) => set(preferences),
}));

const preferencesFile = () => new File(Paths.document, 'chat-preferences.json');

function valid(value: unknown): ChatPreferences | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Partial<ChatPreferences>;
  const sendSide: SendSide = raw.sendSide === 'left' ? 'left' : 'right';
  const background = raw.background;
  if (background?.kind === 'builtin' && BUILTIN_BACKGROUND_IDS.includes(background.id)) {
    return { sendSide, background };
  }
  if (background?.kind === 'photo' && typeof background.uri === 'string' && background.uri) {
    return { sendSide, background };
  }
  return { sendSide, background: { kind: 'none' } };
}

/** Apply the saved chat look (call once at startup, before the first chat renders). */
export function hydrateChatPreferences(): void {
  try {
    const file = preferencesFile();
    if (!file.exists) return;
    const saved = valid(JSON.parse(file.textSync()));
    if (saved) useChatPreferences.getState().set(saved);
  } catch {
    // Keep the defaults.
  }
}

export function saveChatPreferences(preferences: ChatPreferences): void {
  useChatPreferences.getState().set(preferences);
  try {
    preferencesFile().writeSync(JSON.stringify(preferences));
  } catch {
    // Applies until the app closes.
  }
}

/** Copy a trip photo into the app's documents and use it as the chat background. */
export async function applyTripPhotoBackground(
  mediaId: string,
  url: string,
  current: ChatPreferences,
): Promise<void> {
  const folder = new Directory(Paths.document, 'chat-backgrounds');
  if (!folder.exists) folder.create({ intermediates: true });
  const target = new File(folder, `${mediaId}.jpg`);
  if (!target.exists) await File.downloadFileAsync(url, target);
  // The previous trip photo isn't needed any more.
  if (current.background.kind === 'photo' && current.background.mediaId !== mediaId) {
    try {
      new File(current.background.uri).delete();
    } catch {
      // Already gone.
    }
  }
  saveChatPreferences({ ...current, background: { kind: 'photo', uri: target.uri, mediaId } });
}
