// Read-heavy API mix with writes (BL-6.04; NFR-001, NFR-005).
// Thresholds are the NFR-001 targets: reads p95 < 300 ms, writes p95 < 500 ms, feed p95 < 300 ms.
import http from 'k6/http';
import { check, group, sleep } from 'k6';

import { authed, BASE_URL, guard, tokenFor, uuid } from './lib.js';

export const options = {
  scenarios: {
    ramp: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: __ENV.RAMP || '2m', target: Number(__ENV.VUS || 50) },
        { duration: __ENV.HOLD || '5m', target: Number(__ENV.VUS || 50) },
        { duration: '1m', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    'http_req_duration{kind:read}': ['p(95)<300'],
    'http_req_duration{kind:write}': ['p(95)<500'],
    'http_req_duration{name:feed}': ['p(95)<300'],
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
  },
};

const DESTINATION_PATH = __ENV.DESTINATION_PATH || 'portugal/lisbon';

export function setup() {
  guard();
  const destination = http.get(
    `${BASE_URL}/v1/destinations/lookup?path=${encodeURIComponent(DESTINATION_PATH)}`,
    { tags: { name: 'setup' } },
  );
  check(destination, { 'destination exists': (r) => r.status === 200 });
  return { destinationId: destination.json('id') };
}

const tokens = {};

export default function (data) {
  const token = tokens[__VU] || (tokens[__VU] = tokenFor(__VU));
  const read = (name) => ({ ...authed(token, name), tags: { name, kind: 'read' } });
  const write = (name) => ({ ...authed(token, name), tags: { name, kind: 'write' } });

  group('browse', () => {
    const feed = http.get(`${BASE_URL}/v1/feed?destination_id=${data.destinationId}&limit=20`, read('feed'));
    check(feed, { 'feed 200': (r) => r.status === 200 });
    const posts = feed.status === 200 ? feed.json('data') || [] : [];
    if (posts.length) {
      const post = posts[Math.floor(Math.random() * posts.length)];
      check(http.get(`${BASE_URL}/v1/posts/${post.id}`, read('post')), {
        'post 200': (r) => r.status === 200,
      });
      check(http.get(`${BASE_URL}/v1/posts/${post.id}/comments?limit=20`, read('comments')), {
        'comments 200': (r) => r.status === 200,
      });
    }
    check(http.get(`${BASE_URL}/v1/notifications/unread-count`, read('unread')), {
      'unread 200': (r) => r.status === 200,
    });
  });

  // One in ten iterations writes: a post and a reaction (idempotent by key).
  if (Math.random() < 0.1) {
    group('write', () => {
      const created = http.post(
        `${BASE_URL}/v1/posts`,
        JSON.stringify({
          kind: 'tip',
          body: `Load test tip ${uuid()}: the early tram is quieter.`,
          visibility: 'public',
          location_precision: 'destination',
          destination_id: data.destinationId,
        }),
        { ...write('post_create'), headers: { ...write('post_create').headers, 'Idempotency-Key': uuid() } },
      );
      check(created, { 'post 201': (r) => r.status === 201 });
      if (created.status === 201) {
        const reaction = http.post(
          `${BASE_URL}/v1/posts/${created.json('id')}/reactions`,
          JSON.stringify({ reaction: 'like' }),
          write('reaction'),
        );
        check(reaction, { 'reaction ok': (r) => r.status === 200 || r.status === 201 });
      }
    });
  }
  sleep(Number(__ENV.THINK_SECONDS || 1));
}
