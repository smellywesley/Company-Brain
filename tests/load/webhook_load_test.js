import http from 'k6/http';
import { check, sleep } from 'k6';
import crypto from 'k6/crypto';

export const options = {
  stages: [
    { duration: '30s', target: 200 },  // Ramp-up to 200 users
    { duration: '1m', target: 1000 },  // Blast 1,000 concurrent requests
    { duration: '30s', target: 0 },    // Ramp-down to 0
  ],
  thresholds: {
    http_req_duration: ['p(95)<200'],  // 95% of requests must complete below 200ms
    http_req_failed: ['rate<0.01'],    // Error rate must be under 1%
  },
};

// Webhook secrets (matching default staging/test settings)
const SLACK_SIGNING_SECRET = 'change-me-slack-secret';
const GITHUB_WEBHOOK_SECRET = 'change-me-github-secret';

function getSlackHeaders(body) {
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const signatureBase = `v0:${timestamp}:${body}`;
  const signature = 'v0=' + crypto.hmac('sha256', SLACK_SIGNING_SECRET, signatureBase, 'hex');

  return {
    'Content-Type': 'application/json',
    'X-Slack-Request-Timestamp': timestamp,
    'X-Slack-Signature': signature,
  };
}

function getGitHubHeaders(body) {
  const signature = 'sha256=' + crypto.hmac('sha256', GITHUB_WEBHOOK_SECRET, body, 'hex');

  return {
    'Content-Type': 'application/json',
    'X-GitHub-Event': 'pull_request',
    'X-GitHub-Delivery': `dlv-${Math.random().toString(36).substring(7)}`,
    'X-Hub-Signature-256': signature,
  };
}

export default function () {
  const host = __ENV.API_HOST || 'http://localhost:8000';
  
  // ── 1. Slack Webhook Load Test ─────────────────────────────────────────────
  const slackPayload = JSON.stringify({
    token: 'verification-token',
    team_id: 'T012AB34CD',
    api_app_id: 'A0123456',
    event: {
      type: 'message',
      channel: 'C024BE91L',
      user: 'U012AB34CD',
      text: 'Need to approve refund for order ORD-12345 on client Acme',
      ts: (Date.now() / 1000).toString(),
      event_ts: (Date.now() / 1000).toString(),
      channel_type: 'channel'
    },
    type: 'event_callback',
    event_id: `ev-${Math.random().toString(36).substring(7)}`,
    event_time: Math.floor(Date.now() / 1000)
  });

  const slackRes = http.post(`${host}/webhooks/slack`, slackPayload, {
    headers: getSlackHeaders(slackPayload),
  });

  check(slackRes, {
    'Slack webhook status is 200': (r) => r.status === 200,
    'Slack queued event': (r) => r.body.includes('queued') || r.body.includes('ignored'),
  });

  sleep(0.1); // Small delay between virtual user tasks

  // ── 2. GitHub Webhook Load Test ────────────────────────────────────────────
  const githubPayload = JSON.stringify({
    action: 'opened',
    number: 42,
    pull_request: {
      id: Math.floor(Math.random() * 1000000),
      title: 'Fix critical database deadlock in multi-tenancy layer',
      body: 'Resolves transaction deadlocks when writing to Neo4j concurrently.',
      user: { login: 'octocat' },
      created_at: new Date().toISOString(),
      html_url: 'https://github.com/octocat/company-brain/pull/42'
    },
    repository: {
      name: 'company-brain',
      owner: { login: 'octocat' }
    }
  });

  const githubRes = http.post(`${host}/webhooks/github`, githubPayload, {
    headers: getGitHubHeaders(githubPayload),
  });

  check(githubRes, {
    'GitHub webhook status is 200': (r) => r.status === 200,
    'GitHub queued event': (r) => r.body.includes('queued') || r.body.includes('ignored'),
  });

  sleep(0.1);
}
