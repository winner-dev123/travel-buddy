'use client';

import { useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { ExternalLink } from 'lucide-react';
import type { GeoPoint } from '@travelbuddy/domain-types';
import 'maplibre-gl/dist/maplibre-gl.css';

const DEV_STYLE = 'https://demotiles.maplibre.org/style.json';

/**
 * Lazy MapLibre map (ADR-0014): the ~250 KB library loads only when the map scrolls into view.
 * Shows a public reference point (the destination centroid) — never a user location.
 */
export function LocationMap({ center, label, zoom = 10 }: { center: GeoPoint; label: string; zoom?: number }) {
  const t = useTranslations('destination.map');
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const styleUrl = process.env.NEXT_PUBLIC_MAP_STYLE_URL || DEV_STYLE;
  const isDevStyle = styleUrl === DEV_STYLE;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let map: { remove: () => void } | undefined;
    let cancelled = false;
    const observer = new IntersectionObserver(
      async (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        observer.disconnect();
        try {
          const maplibre = await import('maplibre-gl');
          if (cancelled) return;
          // Served from /public (scripts/copy-vendor.mjs): bundlers break MapLibre's own worker URL.
          maplibre.setWorkerUrl('/vendor/maplibre/maplibre-gl-worker.mjs');
          const instance = new maplibre.Map({
            container: el,
            style: styleUrl,
            center: [center.lng, center.lat],
            zoom: isDevStyle ? Math.min(zoom, 5) : zoom,
            attributionControl: { compact: true },
            cooperativeGestures: true,
          });
          instance.addControl(new maplibre.NavigationControl({ showCompass: false }), 'top-right');
          new maplibre.Marker({ color: '#FF735C' }).setLngLat([center.lng, center.lat]).addTo(instance);
          map = instance;
        } catch {
          setFailed(true);
        }
      },
      { rootMargin: '200px' },
    );
    observer.observe(el);
    return () => {
      cancelled = true;
      observer.disconnect();
      map?.remove();
    };
  }, [center.lat, center.lng, zoom, styleUrl, isDevStyle]);

  const osm = `https://www.openstreetmap.org/?mlat=${center.lat}&mlon=${center.lng}#map=11/${center.lat}/${center.lng}`;

  return (
    <div className="overflow-hidden rounded-card border border-border bg-surface">
      <div className="relative aspect-[4/3] bg-surface-muted">
        {/* MapLibre's CSS forces `position: relative` on its container, so it must be an inner
            full-size element rather than the absolutely positioned wrapper itself. */}
        <div className="absolute inset-0">
          <div ref={ref} className="size-full" role="region" aria-label={t('label', { name: label })} />
        </div>
        {failed ? <p className="absolute inset-0 flex items-center justify-center p-4 text-sm text-muted-foreground">{t('failed')}</p> : null}
        {isDevStyle ? (
          <span className="absolute start-2 top-2 rounded bg-black/60 px-2 py-0.5 text-[10px] font-semibold text-white">{t('devStyle')}</span>
        ) : null}
      </div>
      <a href={osm} target="_blank" rel="noopener noreferrer" className="flex items-center justify-between px-4 py-3 text-sm font-semibold text-primary hover:underline">
        {t('openExternal')}
        <ExternalLink className="size-4" aria-hidden="true" />
      </a>
    </div>
  );
}
