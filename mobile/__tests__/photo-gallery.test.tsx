// req: POST-002
import { fireEvent, render, screen } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { PhotoGallery } from '@/features/feed/PhotoGallery';
import type { MediaRef } from '@/features/feed/types';
import { i18n } from '@/i18n';

const photo = (id: string, status: MediaRef['status'] = 'ready'): MediaRef => ({
  id,
  kind: 'image',
  status,
  url: status === 'ready' ? `https://cdn.test/${id}.webp` : null,
  width: 1200,
  height: 800,
  alt_text: null,
});

async function renderGallery(media: MediaRef[], compact: boolean, place?: string) {
  return await render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <PhotoGallery media={media} compact={compact} place={place} />
    </SafeAreaProvider>,
  );
}

beforeEach(async () => {
  await i18n.changeLanguage('en');
});

it('shows the first photo and how many more in lists', async () => {
  await renderGallery([photo('a'), photo('b'), photo('c')], true);
  expect(screen.getByTestId('post-photo-0')).toBeTruthy();
  expect(screen.queryByTestId('post-photo-1')).toBeNull();
  expect(screen.getByTestId('post-more-photos')).toHaveTextContent('+2');
  await fireEvent.press(screen.getByTestId('post-photo-0'));
  expect(screen.queryByTestId('photo-viewer')).toBeNull(); // the card opens the story instead
});

it('names the place on the cover photo of a card', async () => {
  await renderGallery([photo('a'), photo('b')], true, 'Lisbon');
  expect(screen.getByTestId('post-photo-place')).toHaveTextContent('Lisbon');
  // The caption sits on a scrim so it stays readable on a bright photo.
  expect(screen.getByTestId('post-photo-scrim')).toBeTruthy();
});

it('keeps the place readable while the cover is still processing', async () => {
  await renderGallery([photo('a', 'processing')], true, 'Lisbon');
  expect(screen.getByTestId('post-photo-place')).toHaveTextContent('Lisbon');
  expect(screen.queryByTestId('post-photo-scrim')).toBeNull();
});

it('shows no place caption on the story itself', async () => {
  await renderGallery([photo('a')], false, 'Lisbon');
  expect(screen.queryByTestId('post-photo-place')).toBeNull();
});

it('shows every photo on the story and opens one full screen', async () => {
  await renderGallery([photo('a'), photo('b', 'processing'), photo('c')], false);
  expect(screen.getByTestId('post-photo-1')).toHaveTextContent('Photo is processing\u2026');
  await fireEvent.press(screen.getByLabelText('Open photo 3'));
  expect(await screen.findByTestId('photo-viewer')).toBeTruthy();
  // Only ready photos can be viewed: the third photo is the second viewable one.
  expect(screen.getByTestId('photo-viewer-count')).toHaveTextContent('2 of 2');
  await fireEvent.press(screen.getByTestId('photo-viewer-close'));
  expect(screen.queryByTestId('photo-viewer')).toBeNull();
});

it('renders nothing without photos', async () => {
  await renderGallery([], false);
  expect(screen.queryByTestId('post-photos')).toBeNull();
});
