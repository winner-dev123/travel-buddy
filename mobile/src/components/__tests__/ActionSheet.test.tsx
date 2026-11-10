// req: SAFE-002
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { Alert, Platform } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ActionSheetHost, showActions } from '../ActionSheet';

const original = Platform.OS;

async function renderHost() {
  return await render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <ActionSheetHost />
    </SafeAreaProvider>,
  );
}

afterEach(() => {
  Object.defineProperty(Platform, 'OS', { value: original, configurable: true });
  jest.restoreAllMocks();
});

it('shows every action on Android, where the native alert keeps only three', async () => {
  Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
  const alert = jest.spyOn(Alert, 'alert');
  const report = jest.fn();
  await renderHost();
  await act(async () => {
    showActions('Message options', undefined, [
      { text: 'React' },
      { text: 'Reply' },
      { text: 'Cancel', style: 'cancel' },
      { text: 'Reply in thread' },
      { text: 'Report message', onPress: report },
    ]);
  });
  expect(alert).not.toHaveBeenCalled();
  expect(screen.getByTestId('action-sheet')).toHaveTextContent(/Report message/);
  // Cancel is listed last, whatever its position in the menu.
  expect(screen.getByTestId('action-sheet-4')).toHaveTextContent('Cancel');
  await fireEvent.press(screen.getByText('Report message'));
  expect(report).toHaveBeenCalledTimes(1);
  expect(screen.queryByTestId('action-sheet')).toBeNull();
});

it('keeps the native alert for short menus and on iOS', async () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
  showActions('Delete?', undefined, [{ text: 'Cancel', style: 'cancel' }, { text: 'Delete' }]);
  Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
  showActions(
    'React',
    undefined,
    [1, 2, 3, 4, 5].map((n) => ({ text: String(n) })),
  );
  expect(alert).toHaveBeenCalledTimes(2);
});
