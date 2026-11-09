/** Fallback for requests that never reached a locale (rare: the proxy assigns one to every page). */
export default function GlobalNotFound() {
  return (
    <html lang="en">
      <body style={{ fontFamily: 'system-ui, sans-serif', padding: '4rem 1.5rem', textAlign: 'center' }}>
        <h1>Page not found</h1>
        <p>
          {/* Plain link on purpose: this fallback renders outside the localized app. */}
          {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
          <a href="/">Go to the homepage</a>
        </p>
      </body>
    </html>
  );
}
