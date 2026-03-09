#!/usr/bin/env node
import assert from 'node:assert/strict';

process.env.ZENDESK_SUBDOMAIN = 'prod-instance';
process.env.ZENDESK_EMAIL = 'agent@example.com';
process.env.ZENDESK_API_TOKEN = 'test-token';

const {
  zendeskClient,
  runWithRequestContext,
  resolveZendeskTarget,
} = await import(`../src/zendesk-client.js?test=${Date.now()}`);

assert.deepEqual(
  resolveZendeskTarget({ zendeskSubdomain: 'sandbox-instance' }),
  {
    origin: 'https://sandbox-instance.zendesk.com',
    subdomain: 'sandbox-instance',
  },
);

assert.deepEqual(
  resolveZendeskTarget({ zendeskBaseUrl: 'https://sandbox-instance.zendesk.com/api/v2' }),
  {
    origin: 'https://sandbox-instance.zendesk.com',
    subdomain: 'sandbox-instance',
  },
);

assert.throws(
  () => resolveZendeskTarget({ zendeskBaseUrl: 'https://example.com' }),
  /zendesk/i,
);

assert.equal(zendeskClient.getBaseUrl(), 'https://prod-instance.zendesk.com/api/v2');
assert.equal(zendeskClient.getAgentTicketUrl(60612), 'https://prod-instance.zendesk.com/agent/tickets/60612');
assert.equal(zendeskClient.getHelpCenterArticleUrl(44031576754829), 'https://prod-instance.zendesk.com/hc/articles/44031576754829');

await runWithRequestContext({ zendeskSubdomain: 'sandbox-instance' }, async () => {
  assert.equal(zendeskClient.getBaseUrl(), 'https://sandbox-instance.zendesk.com/api/v2');
  assert.equal(zendeskClient.getAgentTicketUrl(60612), 'https://sandbox-instance.zendesk.com/agent/tickets/60612');
  assert.equal(zendeskClient.getHelpCenterArticleUrl(44031576754829), 'https://sandbox-instance.zendesk.com/hc/articles/44031576754829');
});

await runWithRequestContext({ zendeskBaseUrl: 'https://sandbox-instance.zendesk.com/api/v2' }, async () => {
  assert.equal(zendeskClient.getBaseUrl(), 'https://sandbox-instance.zendesk.com/api/v2');
  assert.equal(zendeskClient.getAgentTicketUrl(60612), 'https://sandbox-instance.zendesk.com/agent/tickets/60612');
});

console.log('Zendesk target resolution checks passed.');
