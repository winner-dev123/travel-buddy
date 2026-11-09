/**
 * Accepts only same-origin, root-relative paths ("/feed?tab=nearby"). Anything else — absolute
 * URLs, protocol-relative "//evil.com", backslash tricks, or control characters — falls back.
 * Prevents open redirects through `?next=` parameters.
 */
export function safeNextPath(value: string | null | undefined, fallback = '/feed'): string {
  if (!value || typeof value !== 'string') return fallback;
  if (value.length > 512) return fallback;
  if (!value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) return fallback;
  // Reject any control characters (C0 + DEL) or backslashes anywhere.
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code < 0x20 || code === 0x7f || code === 0x5c) return fallback;
  }
  try {
    const url = new URL(value, 'https://travelbuddy.invalid');
    if (url.origin !== 'https://travelbuddy.invalid') return fallback;
    if (url.pathname.startsWith('/api/')) return fallback;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return fallback;
  }
}
