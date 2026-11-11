import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
  type RefAttributes,
} from 'react';
import { Linking, StyleSheet, View } from 'react-native';
import WebViewBase, { type WebViewMessageEvent, type WebViewProps } from 'react-native-webview';
import type { ShouldStartLoadRequest } from 'react-native-webview/lib/WebViewTypes';

import { scrims } from '@/theme/tokens';
import { useAppTheme } from '@/theme/useAppTheme';
import { useReduceMotion } from '@/theme/useReduceMotion';

import {
  buildMapPage,
  commandScript,
  parseMapMessage,
  type GeoPoint,
  type MapCommand,
  type MapPin,
} from './mapPage';

interface MapHandle {
  injectJavaScript: (script: string) => void;
}
// The library's class typing defaults its generic to `undefined`, which makes every prop `never`.
const WebView = WebViewBase as unknown as ComponentType<WebViewProps & RefAttributes<MapHandle>>;

/** Attribution links in the map open in the browser; nothing else may leave the page. */
const ATTRIBUTION_HOSTS = new Set([
  'openfreemap.org',
  'www.openfreemap.org',
  'openmaptiles.org',
  'www.openmaptiles.org',
  'openstreetmap.org',
  'www.openstreetmap.org',
  'maplibre.org',
]);

function handleNavigation(request: ShouldStartLoadRequest): boolean {
  if (request.url.startsWith('about:') || request.url.startsWith('data:')) return true;
  try {
    const url = new URL(request.url);
    if (url.protocol === 'https:' && ATTRIBUTION_HOSTS.has(url.hostname)) {
      void Linking.openURL(url.toString());
    }
  } catch {
    // not a URL: refuse it
  }
  return false;
}

export interface CompanionMapProps {
  /** Who the map is centred on; null shows the world until a place is known. */
  view: { center: GeoPoint; radiusM: number } | null;
  /** Changes each time a search starts: the radar sweeps, and pins that arrive appear in turn. */
  scanId: number;
  /** A search is running. When it ends without pins (it failed), the radar stops. */
  scanning: boolean;
  /** Travellers to show; null for none yet. */
  pins: MapPin[] | null;
  /** A traveller's pin was tapped (only ids among `pins` are passed on). */
  onOpen: (id: string) => void;
  /** The map couldn't load (offline, no WebGL); `false` once it draws. */
  onUnavailable?: (unavailable: boolean) => void;
  height: number;
  accessibilityLabel: string;
  /** Overlays drawn on top of the map (chips, legends). */
  children?: ReactNode;
}

/** The Companions map (ADR-0030): a WebView running MapLibre, driven by props. */
export function CompanionMap({
  view,
  scanId,
  scanning,
  pins,
  onOpen,
  onUnavailable,
  height,
  accessibilityLabel,
  children,
}: CompanionMapProps) {
  const theme = useAppTheme();
  const reduceMotion = useReduceMotion();
  const ref = useRef<MapHandle>(null);
  const [ready, setReady] = useState(false);
  const html = useMemo(
    () =>
      buildMapPage({
        scheme: theme.scheme,
        colors: {
          background: theme.colors.background,
          primary: theme.colors.primary,
          onPrimary: theme.colors.onPrimary,
          textPrimary: scrims.onPhoto, // names sit on a dark chip in both themes
          scrim: scrims.photoChip,
        },
        reduceMotion,
      }),
    [theme, reduceMotion],
  );
  const known = useMemo(() => new Set((pins ?? []).map((pin) => pin.id)), [pins]);

  const send = (command: MapCommand) => ref.current?.injectJavaScript(commandScript(command));

  const shownView = useRef<string | null>(null);
  const viewKey = view ? `${view.center.lat},${view.center.lng},${view.radiusM}` : null;
  useEffect(() => {
    if (!ready || !view || viewKey === shownView.current) return;
    send({
      type: 'view',
      center: view.center,
      radiusM: view.radiusM,
      animate: shownView.current !== null,
    });
    shownView.current = viewKey;
    // `view` is read through its key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, viewKey]);

  // Declared before the pins effect: when a search and its results land in one render, the
  // sweep starts first and then reveals them.
  const sentScan = useRef(0);
  useEffect(() => {
    if (!ready || scanId === sentScan.current) return;
    sentScan.current = scanId;
    send({ type: 'scan' });
  }, [ready, scanId]);

  const wasScanning = useRef(false);
  useEffect(() => {
    if (!ready) return;
    // A search that failed leaves no pins: stop the beam.
    if (!scanning && wasScanning.current && !pins) send({ type: 'stop' });
    wasScanning.current = scanning;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, scanning]);

  useEffect(() => {
    if (!ready) return;
    send(pins ? { type: 'pins', pins } : { type: 'clear' });
  }, [ready, pins]);

  const onMessage = (event: WebViewMessageEvent) => {
    const message = parseMapMessage(event.nativeEvent.data);
    if (!message) return;
    switch (message.type) {
      case 'ready':
        // A fresh page: show the view again; sweep only if a search is still running.
        shownView.current = null;
        sentScan.current = scanning ? -1 : scanId;
        wasScanning.current = scanning;
        setReady(true);
        break;
      case 'loaded':
        onUnavailable?.(false);
        break;
      case 'error':
        onUnavailable?.(true);
        break;
      case 'open':
        if (known.has(message.id)) onOpen(message.id);
        break;
      default:
        break;
    }
  };

  return (
    <View
      style={[
        styles.frame,
        {
          height,
          borderRadius: theme.radii.xl,
          borderColor: theme.colors.divider,
          backgroundColor: theme.colors.background,
        },
      ]}
    >
      <WebView
        ref={ref}
        testID="companion-map"
        accessibilityLabel={accessibilityLabel}
        source={{ html }}
        originWhitelist={['about:*', 'data:*']}
        onShouldStartLoadWithRequest={handleNavigation}
        onLoadStart={() => setReady(false)}
        onMessage={onMessage}
        javaScriptEnabled
        domStorageEnabled={false}
        geolocationEnabled={false}
        allowFileAccess={false}
        allowsLinkPreview={false}
        setSupportMultipleWindows={false}
        mixedContentMode="never"
        textZoom={100}
        nestedScrollEnabled
        scrollEnabled={false}
        bounces={false}
        overScrollMode="never"
        showsHorizontalScrollIndicator={false}
        showsVerticalScrollIndicator={false}
        style={[styles.web, { backgroundColor: theme.colors.background }]}
      />
      <View pointerEvents="box-none" style={StyleSheet.absoluteFill}>
        {children}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { overflow: 'hidden', borderWidth: StyleSheet.hairlineWidth },
  web: { flex: 1 },
});
