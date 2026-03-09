import { z } from 'zod';
import { zendeskClient } from '../zendesk-client.js';

const ARTICLE_QUERY_HINT = /\b(article|articles|help center|help centre|knowledge base|kb)\b/i;
const TICKET_QUERY_HINT = /\bticket|tickets\b/i;
const ABOUT_QUOTED_TEXT = /\b(?:about|for)\s+['"]([^'"]+)['"]/i;

function resultUrl(r) {
  if (r.result_type === 'ticket') {
    return zendeskClient.getAgentTicketUrl(r.id);
  }
  if (r.html_url) return r.html_url;
  return null;
}

function inferMode(query) {
  const hasArticleHint = ARTICLE_QUERY_HINT.test(query) || /\btype:article\b/i.test(query);
  const hasTicketHint = TICKET_QUERY_HINT.test(query) || /\btype:ticket\b/i.test(query);
  if (hasArticleHint && !hasTicketHint) return 'articles';
  if (hasTicketHint && !hasArticleHint) return 'tickets';
  return 'general';
}

function normalizeWhitespace(value) {
  return value.replace(/\s+/g, ' ').trim();
}

function extractQuotedTopic(query) {
  const match = query.match(ABOUT_QUOTED_TEXT);
  return match?.[1]?.trim() || null;
}

function normalizeTicketQuery(query) {
  if (/\btype:ticket\b/i.test(query)) {
    return normalizeWhitespace(query);
  }

  const topic = extractQuotedTopic(query);
  const filters = ['type:ticket'];
  let text = query;

  if (/\bopen tickets?\b/i.test(text)) {
    filters.push('status:open');
    text = text.replace(/\bopen tickets?\b/gi, ' ');
  }

  text = text
    .replace(/\bsearch zendesk\b/gi, ' ')
    .replace(/\bsearch\b/gi, ' ')
    .replace(/\bzendesk\b/gi, ' ')
    .replace(/\btickets?\b/gi, ' ')
    .replace(/\bsorted by updated date\b/gi, ' ')
    .replace(/\bmost recent\b/gi, ' ')
    .replace(/\blatest\b/gi, ' ')
    .replace(/\babout\b/gi, ' ')
    .replace(/\bfor\b/gi, ' ');

  const keywords = normalizeWhitespace(topic || text);
  return normalizeWhitespace(`${filters.join(' ')} ${keywords}`);
}

function normalizeArticleQuery(query) {
  const topic = extractQuotedTopic(query);
  let text = query
    .replace(/\btype:article\b/gi, ' ')
    .replace(/\bsearch zendesk\b/gi, ' ')
    .replace(/\bsearch\b/gi, ' ')
    .replace(/\bzendesk\b/gi, ' ')
    .replace(/\bhelp center\b/gi, ' ')
    .replace(/\bhelp centre\b/gi, ' ')
    .replace(/\bknowledge base\b/gi, ' ')
    .replace(/\bkb\b/gi, ' ')
    .replace(/\barticles?\b/gi, ' ')
    .replace(/\babout\b/gi, ' ')
    .replace(/\bfor\b/gi, ' ');

  return normalizeWhitespace(topic || text);
}

function normalizeSearchRequest(query) {
  const mode = inferMode(query);
  if (mode === 'tickets') {
    return { mode, query: normalizeTicketQuery(query) };
  }
  if (mode === 'articles') {
    return { mode, query: normalizeArticleQuery(query) };
  }
  return { mode, query: normalizeWhitespace(query) };
}

function trimResult(r) {
  const base = { id: r.id, result_type: r.result_type, url: resultUrl(r) };
  if (r.result_type === 'ticket') {
    return {
      ...base,
      subject: r.subject, status: r.status, priority: r.priority,
      type: r.type, created_at: r.created_at, updated_at: r.updated_at,
      description: (r.description || '').substring(0, 200),
    };
  }
  if (r.result_type === 'article') {
    return {
      ...base,
      title: r.title, section_id: r.section_id,
      locale: r.locale, draft: r.draft,
      created_at: r.created_at, updated_at: r.updated_at,
    };
  }
  return { ...base, name: r.name || r.title || r.subject };
}

export const searchTools = [
  {
    name: "search",
    description: "Keyword-search Zendesk tickets or Help Center articles. Set scope=tickets for ticket searches and scope=articles for Help Center article searches. Use this only when the user explicitly asks to search; for listing, sorting, pagination, or direct ticket/article lookup, prefer list_tickets, list_articles, get_ticket, or get_article.",
    schema: {
      query: z.string().max(1000).describe("Search keywords or Zendesk query string"),
      scope: z.enum(["all", "tickets", "articles"]).optional().describe("Search scope: tickets for Zendesk tickets, articles for Help Center articles, or all for mixed search"),
      sort_by: z.string().optional().describe("Field to sort by"),
      sort_order: z.enum(["asc", "desc"]).optional().describe("Sort order (asc or desc)"),
      page: z.number().min(1).optional().describe("Page number for pagination"),
      per_page: z.number().min(1).max(100).optional().describe("Number of results per page (1-100)")
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true },
    handler: async ({ query, scope, sort_by, sort_order, page, per_page }) => {
      try {
        const params = { sort_by, sort_order, page, per_page };
        const normalized = scope && scope !== 'all'
          ? normalizeSearchRequest(`${scope} ${query}`)
          : normalizeSearchRequest(query);
        const result = normalized.mode === 'articles'
          ? await zendeskClient.searchArticles(normalized.query, params)
          : await zendeskClient.search(normalized.query, params);
        const results = (result.results || []).map(trimResult);
        const summary = {
          query: normalized.query,
          scope: normalized.mode,
          count: result.count ?? results.length,
          next_page: result.next_page,
          results
        };
        return {
          content: [{ type: "text", text: JSON.stringify(summary, null, 2) }]
        };
      } catch (error) {
        return {
          content: [{ type: "text", text: `Error searching: ${error.message}` }],
          isError: true
        };
      }
    }
  }
];
