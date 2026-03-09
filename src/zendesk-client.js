import axios from 'axios';
import { AsyncLocalStorage } from 'node:async_hooks';

const SUBDOMAIN_REGEX = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/i;
const ZENDESK_HOST_SUFFIX = '.zendesk.com';

export const authContext = new AsyncLocalStorage();

export function runWithAuth(authHeader, fn) {
  return runWithRequestContext({ authorization: authHeader }, fn);
}

export function runWithRequestContext(context, fn) {
  return authContext.run({
    authorization: context?.authorization || null,
    zendeskSubdomain: context?.zendeskSubdomain || null,
    zendeskBaseUrl: context?.zendeskBaseUrl || null,
  }, fn);
}

function validateSubdomain(subdomain, label = 'Zendesk subdomain') {
  if (!SUBDOMAIN_REGEX.test(subdomain)) {
    throw new Error(`Invalid ${label} format. Must be alphanumeric with optional hyphens.`);
  }
}

function normalizeZendeskOriginFromSubdomain(subdomain, label = 'Zendesk subdomain') {
  validateSubdomain(subdomain, label);
  return `https://${subdomain}.zendesk.com`;
}

function normalizeZendeskOriginFromBaseUrl(baseUrl, label = 'Zendesk base URL') {
  let parsed;
  try {
    parsed = new URL(baseUrl);
  } catch {
    throw new Error(`Invalid ${label}. Must be a valid https://<subdomain>.zendesk.com URL.`);
  }

  if (parsed.protocol !== 'https:') {
    throw new Error(`Invalid ${label}. Only https URLs are allowed.`);
  }

  if (!parsed.hostname.endsWith(ZENDESK_HOST_SUFFIX)) {
    throw new Error(`Invalid ${label}. Host must end with ${ZENDESK_HOST_SUFFIX}.`);
  }

  const subdomain = parsed.hostname.slice(0, -ZENDESK_HOST_SUFFIX.length);
  validateSubdomain(subdomain, label);

  return `https://${parsed.hostname}`;
}

export function resolveZendeskTarget({
  zendeskSubdomain,
  zendeskBaseUrl,
  defaultSubdomain,
  defaultBaseUrl,
} = {}) {
  if (zendeskSubdomain && zendeskBaseUrl) {
    const originFromSubdomain = normalizeZendeskOriginFromSubdomain(zendeskSubdomain, 'Zendesk subdomain');
    const originFromBaseUrl = normalizeZendeskOriginFromBaseUrl(zendeskBaseUrl, 'Zendesk base URL');
    if (originFromSubdomain !== originFromBaseUrl) {
      throw new Error('Zendesk subdomain and base URL point to different accounts.');
    }

    return { origin: originFromBaseUrl, subdomain: zendeskSubdomain };
  }

  if (zendeskBaseUrl) {
    const origin = normalizeZendeskOriginFromBaseUrl(zendeskBaseUrl, 'Zendesk base URL');
    const subdomain = new URL(origin).hostname.slice(0, -ZENDESK_HOST_SUFFIX.length);
    return { origin, subdomain };
  }

  if (zendeskSubdomain) {
    return {
      origin: normalizeZendeskOriginFromSubdomain(zendeskSubdomain, 'Zendesk subdomain'),
      subdomain: zendeskSubdomain,
    };
  }

  if (defaultBaseUrl || defaultSubdomain) {
    return resolveZendeskTarget({
      zendeskSubdomain: defaultSubdomain,
      zendeskBaseUrl: defaultBaseUrl,
    });
  }

  return { origin: null, subdomain: null };
}

class RateLimiter {
  constructor(maxPerMinute) {
    this.maxPerMinute = maxPerMinute;
    this.timestamps = [];
  }

  async acquire() {
    const now = Date.now();
    this.timestamps = this.timestamps.filter(t => now - t < 60000);
    if (this.timestamps.length >= this.maxPerMinute) {
      const waitMs = 60000 - (now - this.timestamps[0]);
      throw new Error(`Rate limit reached (${this.maxPerMinute}/min). Retry after ${Math.ceil(waitMs / 1000)}s.`);
    }
    this.timestamps.push(now);
  }
}

class ZendeskClient {
  constructor() {
    this.subdomain = process.env.ZENDESK_SUBDOMAIN;
    this.baseUrl = process.env.ZENDESK_BASE_URL;
    this.email = process.env.ZENDESK_EMAIL;
    this.apiToken = process.env.ZENDESK_API_TOKEN;

    const defaultTarget = resolveZendeskTarget({
      zendeskSubdomain: this.subdomain,
      zendeskBaseUrl: this.baseUrl,
    });
    this.subdomain = defaultTarget.subdomain;
    this.origin = defaultTarget.origin;

    if (!this.subdomain || !this.email || !this.apiToken) {
      console.error('[zendesk-client] Credentials not found. Set ZENDESK_SUBDOMAIN or ZENDESK_BASE_URL, plus ZENDESK_EMAIL and ZENDESK_API_TOKEN.');
    }

    const rateLimit = parseInt(process.env.ZENDESK_RATE_LIMIT, 10) || 200;
    this.rateLimiter = new RateLimiter(rateLimit);
  }

  getTarget() {
    const store = authContext.getStore();
    return resolveZendeskTarget({
      zendeskSubdomain: store?.zendeskSubdomain,
      zendeskBaseUrl: store?.zendeskBaseUrl,
      defaultSubdomain: this.subdomain,
      defaultBaseUrl: this.origin,
    });
  }

  getOrigin() {
    const target = this.getTarget();
    if (!target.origin) {
      throw new Error('Zendesk target not configured. Provide X-Zendesk-Subdomain or X-Zendesk-Base-Url, or set ZENDESK_SUBDOMAIN/ZENDESK_BASE_URL.');
    }
    return target.origin;
  }

  getSubdomain() {
    return this.getTarget().subdomain;
  }

  getBaseUrl() {
    return `${this.getOrigin()}/api/v2`;
  }

  getAgentTicketUrl(id) {
    return `${this.getOrigin()}/agent/tickets/${id}`;
  }

  getHelpCenterArticleUrl(id) {
    return `${this.getOrigin()}/hc/articles/${id}`;
  }

  getAuthHeader() {
    const store = authContext.getStore();
    if (store?.authorization) {
      return store.authorization;
    }
    const auth = Buffer.from(`${this.email}/token:${this.apiToken}`).toString('base64');
    return `Basic ${auth}`;
  }

  async request(method, endpoint, data = null, params = null) {
    const store = authContext.getStore();
    const hasPerUserAuth = !!store?.authorization;
    const target = this.getTarget();

    if (!hasPerUserAuth && (!this.subdomain || !this.email || !this.apiToken)) {
      throw new Error('Zendesk credentials not configured. Provide Authorization header or set environment variables.');
    }

    if (!target.origin) {
      throw new Error('Zendesk target not configured. Provide X-Zendesk-Subdomain or X-Zendesk-Base-Url, or set ZENDESK_SUBDOMAIN/ZENDESK_BASE_URL.');
    }

    await this.rateLimiter.acquire();

    const url = `${this.getBaseUrl()}${endpoint}`;
    const headers = {
      'Authorization': this.getAuthHeader(),
    };

    const config = { method, url, headers, params, timeout: 30000, maxContentLength: 10 * 1024 * 1024, maxBodyLength: 10 * 1024 * 1024 };

    if (data !== null && data !== undefined) {
      config.data = data;
      headers['Content-Type'] = 'application/json';
    }

    try {
      const response = await axios(config);

      return response.data;
    } catch (error) {
      if (error.response) {
        const status = error.response.status;
        const fullBody = JSON.stringify(error.response.data);
        const errorType = error.response.data?.error || 'Request failed';
        const description = error.response.data?.description || '';
        const details = error.response.data?.details;
        const detailMsg = details ? ` Details: ${JSON.stringify(details)}` : '';
        console.error(`[zendesk-client] API error: ${status} on ${method} ${endpoint} - body: ${fullBody}`);
        throw new Error(`Zendesk API Error: ${status} - ${errorType}. ${description}${detailMsg}`);
      }
      if (error.code === 'ECONNABORTED') {
        throw new Error('Zendesk API request timed out after 30s');
      }
      throw new Error(`Zendesk connection error: ${error.message}`);
    }
  }

  // Tickets
  async listTickets(params) { return this.request('GET', '/tickets.json', null, params); }
  async getTicket(id) { return this.request('GET', `/tickets/${id}.json`); }
  async createTicket(data) { return this.request('POST', '/tickets.json', { ticket: data }); }
  async updateTicket(id, data) { return this.request('PUT', `/tickets/${id}.json`, { ticket: data }); }

  // Help Center
  async listArticles(params) { return this.request('GET', '/help_center/articles.json', null, params); }
  async getArticle(id) { return this.request('GET', `/help_center/articles/${id}.json`); }
  async searchArticles(query, params = {}) {
    return this.request('GET', '/help_center/articles/search.json', null, { query, ...params });
  }
  async createArticle(data, sectionId) { return this.request('POST', `/help_center/sections/${sectionId}/articles.json`, { article: data }); }
  async updateArticle(id, data) {
    const translationFields = ['title', 'body', 'locale'];
    const metadataFields = ['draft', 'permission_group_id', 'user_segment_id', 'label_names'];

    const translationData = {};
    const metaData = {};
    let hasTranslation = false;
    let hasMeta = false;

    for (const key of translationFields) {
      if (data[key] !== undefined) { translationData[key] = data[key]; hasTranslation = true; }
    }
    for (const key of metadataFields) {
      if (data[key] !== undefined) { metaData[key] = data[key]; hasMeta = true; }
    }

    let result;
    if (hasTranslation) {
      const locale = data.locale || 'en-us';
      result = await this.request('PUT', `/help_center/articles/${id}/translations/${locale}.json`, { translation: translationData });
    }
    if (hasMeta) {
      result = await this.request('PUT', `/help_center/articles/${id}.json`, { article: metaData });
    }
    if (!hasTranslation && !hasMeta) {
      result = await this.request('PUT', `/help_center/articles/${id}.json`, { article: data });
    }
    return result;
  }

  // Search
  async search(query, params = {}) { return this.request('GET', '/search.json', null, { query, ...params }); }
}

export const zendeskClient = new ZendeskClient();
