import type { HttpMethod } from '../core/types';

export interface RouteMatch<H> {
  handler: H;
  params: Record<string, string>;
}

interface Route<H> {
  method: HttpMethod | '*';
  segments: string[];
  handler: H;
}

/** Minimal path router: `/v1/posts/:id/reactions/me`, with `*` as a trailing wildcard. */
export class Router<H> {
  private readonly routes: Route<H>[] = [];

  add(method: HttpMethod | '*', pattern: string, handler: H): this {
    this.routes.push({ method, segments: pattern.split('/').filter(Boolean), handler });
    return this;
  }

  match(method: HttpMethod, path: string): RouteMatch<H> | null {
    const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
    for (const route of this.routes) {
      if (route.method !== '*' && route.method !== method) continue;
      const params: Record<string, string> = {};
      let ok = true;
      for (let i = 0; i < route.segments.length; i++) {
        const seg = route.segments[i] as string;
        if (seg === '*') {
          return { handler: route.handler, params };
        }
        const part = parts[i];
        if (part === undefined) {
          ok = false;
          break;
        }
        if (seg.startsWith(':')) params[seg.slice(1)] = part;
        else if (seg !== part) {
          ok = false;
          break;
        }
      }
      if (ok && parts.length === route.segments.length) return { handler: route.handler, params };
    }
    return null;
  }
}
