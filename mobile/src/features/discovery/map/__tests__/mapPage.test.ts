// req: DISC-004, LOC-010, NFR-008
import {
  buildMapPage,
  commandScript,
  MAPLIBRE_SCRIPT,
  MAPLIBRE_STYLESHEET,
  MAP_STYLES,
  parseMapMessage,
  type MapCommand,
} from '../mapPage';

const options = {
  scheme: 'dark' as const,
  colors: {
    background: '#0B0B0D',
    primary: '#D9B56C',
    onPrimary: '#1B1404',
    textPrimary: '#FFFFFF',
    scrim: 'rgba(11,11,13,0.72)',
  },
  reduceMotion: false,
};

describe('map page', () => {
  const html = buildMapPage(options);

  it('loads a pinned MapLibre build checked with Subresource Integrity', () => {
    expect(MAPLIBRE_SCRIPT.url).toMatch(/maplibre-gl@\d+\.\d+\.\d+\/dist\/maplibre-gl\.js$/);
    expect(html).toContain(
      `src="${MAPLIBRE_SCRIPT.url}" integrity="${MAPLIBRE_SCRIPT.integrity}" crossorigin="anonymous"`,
    );
    expect(html).toContain(
      `href="${MAPLIBRE_STYLESHEET.url}" integrity="${MAPLIBRE_STYLESHEET.integrity}"`,
    );
    expect(MAPLIBRE_SCRIPT.integrity).toMatch(/^sha384-[A-Za-z0-9+/]{64}$/);
  });

  it('can reach only the CDN and the tile server, and never asks for the device location', () => {
    expect(html).toContain("default-src 'none'");
    expect(html).toContain('connect-src https://tiles.openfreemap.org;');
    expect(html).toContain("form-action 'none'");
    expect(html).not.toMatch(/geolocation|getCurrentPosition|watchPosition/);
    expect(html).not.toMatch(/innerHTML|insertAdjacentHTML|document\.write/);
  });

  it('uses the style that matches the theme', () => {
    expect(html).toContain(MAP_STYLES.dark);
    expect(buildMapPage({ ...options, scheme: 'light' })).toContain(MAP_STYLES.light);
  });

  it('honours reduce motion', () => {
    expect(html).toContain('"reduceMotion":false');
    expect(buildMapPage({ ...options, reduceMotion: true })).toContain('"reduceMotion":true');
  });

  it('passes names to the page as data, never as markup', () => {
    const command: MapCommand = {
      type: 'pins',
      pins: [
        {
          id: 'u1',
          name: '</script><img src=x onerror=alert(1)>',
          initial: '<',
          avatarUrl: null,
          lat: 60.17,
          lng: 24.94,
          label: 'Open profile: "x"',
        },
      ],
    };
    const script = commandScript(command);
    const json = script.slice(script.indexOf('apply(') + 'apply('.length, script.lastIndexOf(');'));
    expect(JSON.parse(json)).toEqual(command);
    expect(script.endsWith(';true;')).toBe(true);
  });

  it('accepts only the messages it expects from the page', () => {
    expect(parseMapMessage('{"type":"ready"}')).toEqual({ type: 'ready' });
    expect(parseMapMessage('{"type":"open","id":"u2"}')).toEqual({ type: 'open', id: 'u2' });
    expect(parseMapMessage('{"type":"error","reason":"webgl"}')).toEqual({
      type: 'error',
      reason: 'webgl',
    });
    expect(parseMapMessage('{"type":"open","id":""}')).toBeNull();
    expect(parseMapMessage(`{"type":"open","id":"${'x'.repeat(65)}"}`)).toBeNull();
    expect(parseMapMessage('{"type":"navigate","url":"https://evil.example"}')).toBeNull();
    expect(parseMapMessage('not json')).toBeNull();
    expect(parseMapMessage('null')).toBeNull();
  });
});
