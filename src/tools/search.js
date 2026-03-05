import { z } from 'zod';
import { zendeskClient } from '../zendesk-client.js';

export const searchTools = [
  {
    name: "search",
    description: "Search across Zendesk tickets, articles, users, and organizations using Zendesk query syntax.",
    schema: {
      query: z.string().max(1000).describe("Search query string (Zendesk search syntax)"),
      sort_by: z.string().optional().describe("Field to sort by"),
      sort_order: z.enum(["asc", "desc"]).optional().describe("Sort order (asc or desc)"),
      page: z.number().min(1).optional().describe("Page number for pagination"),
      per_page: z.number().min(1).max(100).optional().describe("Number of results per page (1-100)")
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true },
    handler: async ({ query, sort_by, sort_order, page, per_page }) => {
      try {
        const params = { sort_by, sort_order, page, per_page };
        const result = await zendeskClient.search(query, params);
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }]
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
