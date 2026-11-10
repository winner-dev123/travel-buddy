import { Alert, Modal, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { create } from 'zustand';

import { useAppTheme } from '@/theme/useAppTheme';

export interface SheetAction {
  text: string;
  style?: 'default' | 'cancel' | 'destructive';
  onPress?: () => void;
}

interface SheetRequest {
  title: string;
  message?: string;
  actions: SheetAction[];
}

const useSheet = create<{
  request: SheetRequest | null;
  setRequest: (request: SheetRequest | null) => void;
}>()((set) => ({ request: null, setRequest: (request) => set({ request }) }));

/**
 * A menu of actions. Android's native alert keeps at most three buttons and silently drops the
 * rest (safety actions such as "Report" included), so longer menus there open an in-app sheet.
 * iOS, and menus of up to three buttons, keep the native alert.
 */
export function showActions(title: string, message: string | undefined, actions: SheetAction[]) {
  if (Platform.OS !== 'android' || actions.length <= 3) {
    Alert.alert(title, message, actions);
    return;
  }
  useSheet.getState().setRequest({ title, message, actions });
}

/** Rendered once in the root layout. */
export function ActionSheetHost() {
  const theme = useAppTheme();
  const insets = useSafeAreaInsets();
  const request = useSheet((state) => state.request);
  const close = () => useSheet.getState().setRequest(null);
  const choose = (action: SheetAction) => {
    close();
    action.onPress?.();
  };
  const ordered = request
    ? [
        ...request.actions.filter((a) => a.style !== 'cancel'),
        ...request.actions.filter((a) => a.style === 'cancel'),
      ]
    : [];
  return (
    <Modal
      visible={request !== null}
      transparent
      animationType="fade"
      onRequestClose={close}
      statusBarTranslucent
    >
      <Pressable style={styles.backdrop} onPress={close} testID="action-sheet-backdrop">
        <Pressable
          style={[
            styles.sheet,
            {
              backgroundColor: theme.colors.surfaceRaised,
              paddingBottom: Math.max(insets.bottom, 12),
            },
          ]}
          accessibilityRole="menu"
          testID="action-sheet"
        >
          {request ? (
            <View style={styles.header}>
              <Text style={[theme.typography.title3, { color: theme.colors.textPrimary }]}>
                {request.title}
              </Text>
              {request.message ? (
                <Text style={[theme.typography.body, { color: theme.colors.textSecondary }]}>
                  {request.message}
                </Text>
              ) : null}
            </View>
          ) : null}
          {ordered.map((action, index) => (
            <Pressable
              key={`${index}-${action.text}`}
              onPress={() => choose(action)}
              accessibilityRole="menuitem"
              style={[styles.action, { borderTopColor: theme.colors.divider }]}
              testID={`action-sheet-${index}`}
            >
              <Text
                style={[
                  theme.typography.body,
                  {
                    color:
                      action.style === 'destructive'
                        ? theme.colors.danger
                        : action.style === 'cancel'
                          ? theme.colors.textSecondary
                          : theme.colors.textPrimary,
                    fontWeight: action.style === 'cancel' ? '600' : '400',
                  },
                ]}
              >
                {action.text}
              </Text>
            </Pressable>
          ))}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.4)' },
  sheet: { borderTopLeftRadius: 16, borderTopRightRadius: 16, paddingTop: 16 },
  header: { paddingHorizontal: 20, paddingBottom: 12, gap: 4 },
  action: { paddingVertical: 14, paddingHorizontal: 20, borderTopWidth: StyleSheet.hairlineWidth },
});
