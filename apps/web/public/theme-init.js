// Applies the saved colour theme before first paint. Served as an external same-origin file so it
// works under a strict nonce CSP on dynamic routes (no inline script needed).
(function () {
  try {
    var saved = localStorage.getItem('tb-theme');
    var mode = saved === 'light' || saved === 'dark' ? saved : 'system';
    var dark = mode === 'dark' || (mode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  } catch {
    /* storage unavailable: the CSS prefers-color-scheme fallback applies */
  }
})();
