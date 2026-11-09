import type { MetadataRoute } from 'next';

/** PWA manifest (brief §1). Offline asset caching for guides arrives with the audio guides phase. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'Travel Buddy',
    short_name: 'Travel Buddy',
    description: 'Discover places, plan trips and connect with travelers worldwide.',
    start_url: '/feed',
    scope: '/',
    display: 'standalone',
    background_color: '#fafaf7',
    theme_color: '#087f8c',
    icons: [{ src: '/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' }],
  };
}
