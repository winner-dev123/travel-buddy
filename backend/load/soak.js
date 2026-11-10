// Soak (BL-6.04; NFR-003): a steady, modest arrival rate for hours to surface leaks, connection
// pool exhaustion, outbox lag and slow drift. Watch GET /v1/admin/ops/summary while it runs.
import http from 'k6/http';
import { check, sleep } from 'k6';

import { authed, BASE_URL, guard, tokenFor } from './lib.js';

export const options = {
  scenarios: {
    steady: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 20), // iterations per second
      timeUnit: '1s',
      duration: __ENV.DURATION || '2h',
      preAllocatedVUs: Number(__ENV.VUS || 40),
      maxVUs: Number(__ENV.MAX_VUS || 200),
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<300', 'p(99)<1000'],
    http_req_failed: ['rate<0.001'],
    dropped_iterations: ['count<100'],
  },
};

export function setup() {
  guard();
}

const tokens = {};

export default function () {
  const token = tokens[__VU] || (tokens[__VU] = tokenFor(__VU));
  const me = http.get(`${BASE_URL}/v1/users/me`, authed(token, 'me'));
  check(me, { 'me 200': (r) => r.status === 200 });
  const conversations = http.get(`${BASE_URL}/v1/conversations?limit=20`, authed(token, 'conversations'));
  check(conversations, { 'conversations 200': (r) => r.status === 200 });
  const groups = http.get(`${BASE_URL}/v1/groups`, authed(token, 'groups'));
  check(groups, { 'groups 200': (r) => r.status === 200 });
  sleep(0.2);
}
