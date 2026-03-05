import axios from 'axios';
import { AsyncLocalStorage } from 'node:async_hooks';

const SUBDOMAIN_REGEX = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/i;

export const authContext = new AsyncLocalStorage();

export function runWithAuth(authHeader, fn) {
  return authContext.run({ authorization: authHeader }, fn);
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
    this.email = process.env.ZENDESK_EMAIL;
    this.apiToken = process.env.ZENDESK_API_TOKEN;

    if (this.subdomain && !SUBDOMAIN_REGEX.test(this.subdomain)) {
      throw new Error('Invalid ZENDESK_SUBDOMAIN format. Must be alphanumeric with optional hyphens.');
    }

    if (!this.subdomain || !this.email || !this.apiToken) {
      console.error('[zendesk-client] Credentials not found. Set ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN.');
    }

    const rateLimit = parseInt(process.env.ZENDESK_RATE_LIMIT, 10) || 200;
    this.rateLimiter = new RateLimiter(rateLimit);
  }

  getBaseUrl() {
    return `https://${this.subdomain}.zendesk.com/api/v2`;
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

    if (!hasPerUserAuth && (!this.subdomain || !this.email || !this.apiToken)) {
      throw new Error('Zendesk credentials not configured. Provide Authorization header or set environment variables.');
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
        const message = error.response.data?.error || error.response.data?.description || 'Request failed';
        console.error(`[zendesk-client] API error: ${status} on ${method} ${endpoint} - body: ${fullBody}`);
        throw new Error(`Zendesk API Error: ${status} - ${message}`);
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
