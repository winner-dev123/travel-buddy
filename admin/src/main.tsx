import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import { KEYS, readItem } from './auth/storage';
import { readConfig } from './config';
import './styles.css';

// Applied before the first paint so a light-theme choice doesn't flash dark.
if (readItem('local', KEYS.theme) === 'light') document.documentElement.dataset.theme = 'light';

const root = createRoot(document.getElementById('root')!);

try {
  const config = readConfig();
  root.render(
    <StrictMode>
      <App config={config} />
    </StrictMode>,
  );
} catch (error) {
  root.render(
    <div className="auth-screen">
      <div className="auth-card">
        <h1>Configuration</h1>
        <p className="muted">{error instanceof Error ? error.message : 'The console is not configured.'}</p>
      </div>
    </div>,
  );
}
