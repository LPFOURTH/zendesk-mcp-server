import { z } from 'zod';
import { zendeskClient } from '../zendesk-client.js';

export const helpCenterTools = [
  {
    name: "list_articles",
    description: "List Help Center articles. Returns paginated results.",
    schema: {
      page: z.number().min(1).optional().describe("Page number for pagination"),
      per_page: z.number().min(1).max(100).optional().describe("Number of articles per page (1-100)"),
      sort_by: z.string().optional().describe("Field to sort by"),
      sort_order: z.enum(["asc", "desc"]).optional().describe("Sort order (asc or desc)")
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true },
    handler: async ({ page, per_page, sort_by, sort_order }) => {
      try {
        const params = {};
        if (page !== undefined) params.page = page;
        if (per_page !== undefined) params.per_page = per_page;
        if (sort_by !== undefined) params.sort_by = sort_by;
        if (sort_order !== undefined) params.sort_order = sort_order;
        const result = await zendeskClient.listArticles(params);
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }]
        };
      } catch (error) {
        return {
          content: [{ type: "text", text: `Error listing articles: ${error.message}` }],
          isError: true
        };
      }
    }
  },
  {
    name: "get_article",
    description: "Get a specific Help Center article by ID, including body content.",
    schema: {
      id: z.number().describe("Article ID")
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true },
    handler: async ({ id }) => {
      try {
        const result = await zendeskClient.getArticle(id);
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }]
        };
      } catch (error) {
        return {
          content: [{ type: "text", text: `Error getting article: ${error.message}` }],
          isError: true
        };
      }
    }
  },
  {
    name: "create_article",
    description: "Create a new Help Center article in a specified section.",
    schema: {
      title: z.string().max(500).describe("Article title"),
      body: z.string().max(1048576).describe("Article body content (HTML)"),
      section_id: z.number().describe("Section ID where the article will be created"),
      locale: z.string().max(10).optional().describe("Article locale (e.g., 'en-us')"),
      draft: z.boolean().optional().describe("Whether the article is a draft"),
      permission_group_id: z.number().optional().describe("Permission group ID for the article"),
      user_segment_id: z.number().optional().describe("User segment ID for the article"),
      label_names: z.array(z.string().max(100)).max(20).optional().describe("Labels for the article")
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false },
    handler: async ({ title, body, section_id, locale, draft, permission_group_id, user_segment_id, label_names }) => {
      try {
        const articleData = { title, body };
        if (locale !== undefined) articleData.locale = locale;
        if (draft !== undefined) articleData.draft = draft;
        if (permission_group_id !== undefined) articleData.permission_group_id = permission_group_id;
        articleData.user_segment_id = user_segment_id !== undefined ? user_segment_id : null;
        if (label_names !== undefined) articleData.label_names = label_names;
        const result = await zendeskClient.createArticle(articleData, section_id);
        return {
          content: [{ type: "text", text: `Article created successfully!\n\n${JSON.stringify(result, null, 2)}` }]
        };
      } catch (error) {
        return {
          content: [{ type: "text", text: `Error creating article: ${error.message}` }],
          isError: true
        };
      }
    }
  },
  {
    name: "update_article",
    description: "Update an existing Help Center article. Only provided fields will be changed.",
    schema: {
      id: z.number().describe("Article ID to update"),
      title: z.string().max(500).optional().describe("Updated article title"),
      body: z.string().max(1048576).optional().describe("Updated article body content (HTML)"),
      locale: z.string().max(10).optional().describe("Updated article locale (e.g., 'en-us')"),
      draft: z.boolean().optional().describe("Whether the article is a draft"),
      permission_group_id: z.number().optional().describe("Updated permission group ID"),
      user_segment_id: z.number().optional().describe("Updated user segment ID"),
      label_names: z.array(z.string().max(100)).max(20).optional().describe("Updated labels")
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true },
    handler: async ({ id, title, body, locale, draft, permission_group_id, user_segment_id, label_names }) => {
      try {
        const articleData = {};
        if (title !== undefined) articleData.title = title;
        if (body !== undefined) articleData.body = body;
        if (locale !== undefined) articleData.locale = locale;
        if (draft !== undefined) articleData.draft = draft;
        if (permission_group_id !== undefined) articleData.permission_group_id = permission_group_id;
        if (user_segment_id !== undefined) articleData.user_segment_id = user_segment_id;
        if (label_names !== undefined) articleData.label_names = label_names;

        const result = await zendeskClient.updateArticle(id, articleData);
        const article = result?.article || result?.translation || result;
        return {
          content: [{ type: "text", text: `Article updated successfully!\n\n${JSON.stringify({ article }, null, 2)}` }]
        };
      } catch (error) {
        return {
          content: [{ type: "text", text: `Error updating article: ${error.message}` }],
          isError: true
        };
      }
    }
  }
];
