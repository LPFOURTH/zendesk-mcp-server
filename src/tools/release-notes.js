import { z } from 'zod';
import { zendeskClient } from '../zendesk-client.js';

// ---------------------------------------------------------------------------
// HTML template constants – ported verbatim from zendesk_constants.py
// ---------------------------------------------------------------------------

const US_TEMPLATE_HEADER = `<h2 class="first:mt-1.5">What's New?</h2>

<p>
  <span class="wysiwyg-font-size-medium">
    Use the links below to find out more about each item release for 
    <a href="#h_01JQXYFHC80BWHZKT57J5HNC7N">Labor Main</a>, 
    <a href="#h_01JQXYFHC8R57QW1SDFY29RW86">Platform</a>, and 
    <a href="#h_01JQXYVPMAK8ZP2EWXW9A58577">General Improvements</a>
  </span>
</p>

<p>
  <span class="wysiwyg-font-size-medium"><strong>Release date:</strong> DD Month name YYYY</span>
</p>

<p>&nbsp;</p>

<h2 id="h_01JQXYFHC80BWHZKT57J5HNC7N">Labor Main</h2>
<p>&nbsp;</p>

<h2 id="h_01JQXYFHC8R57QW1SDFY29RW86">Platform</h2>
<p>&nbsp;</p>
<h2 id="h_01JQXYVPMAK8ZP2EWXW9A58577">General Improvements</h2>
<p>A list of defect/bug fixes</p>
<p>&nbsp;</p>
<h2>All features - move them to the right place</h2>
`;

const US_TEMPLATE_MIDDLE = `
<p>
  <span class="wysiwyg-font-size-medium">---------------------------------------------------------------</span>
</p>

<p class="first:mt-1.5">
  <em>
    <strong>
      <span class="wysiwyg-font-size-medium wysiwyg-color-black">
        This information will be removed from here and used to create separate articles for each feature
      </span>
    </strong>
  </em>
</p>

<h2 class="first:mt-1.5">Release Note Info/Steps</h2>
`;

const TEMPLATE_FEATURE_DETAILS_FOOTER = `
<ul>
  <li><span class="wysiwyg-font-size-medium">Enabled by default? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Set up by customer admin? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Enable via support ticket? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Affects configuration or data? - Y/N</span></li>
  <li><span class="wysiwyg-font-size-medium">Roles affected: If applicable</span></li>
</ul>

<h2>Instructions/Screenshots</h2>

<p>
  <span class="wysiwyg-font-size-medium">
    Description and instructions for enabling (if applicable) and using the new/changed functionality. If there's a large amount of information, include headers (which can be turned into a table of contents if required).
  </span>
</p>

<p>&nbsp;</p>
`;

const UK_TEMPLATE_HEADER = `
<h2 class="first:mt-1.5">What's New?</h2>
`;

const UK_TEMPLATE_MIDDLE = `
<p>
  <span class="wysiwyg-font-size-medium">
    Use the links above to find out more about this release.
  </span>
</p>
<p>
  <span class="wysiwyg-font-size-medium">
    <strong>Release date:</strong> DD Month name YYYY
  </span>
</p>
<p>&nbsp;</p>

<p>
  <span class="wysiwyg-font-size-medium">---------------------------------------------------------------</span>
</p>

<p class="first:mt-1.5">
  <em>
    <strong>
      <span class="wysiwyg-font-size-medium wysiwyg-color-black">
        This information will be removed from here and used to create separate articles for each feature
      </span>
    </strong>
  </em>
</p>

<h2 class="first:mt-1.5">Release Note Info/Steps</h2>
`;

// ---------------------------------------------------------------------------
// Markdown parsing helpers – ported from zendesk_utils.py
// ---------------------------------------------------------------------------

function normalizeMarkdown(markdownContent) {
  return markdownContent
    .trim()
    .split('\n')
    .map(line => line.trimStart())
    .join('\n');
}

function findSectionHeaders(normalizedMd) {
  const pattern = /^###\s*(?<header>[^\n]+)\s*$/gm;
  const matches = [];
  let m;
  while ((m = pattern.exec(normalizedMd)) !== null) {
    matches.push({
      header: m.groups.header.trim(),
      start: m.index,
      end: m.index + m[0].length,
      fullMatch: m[0]
    });
  }
  return matches;
}

function extractSectionContent(headerMatch, headers, index, normalizedMd) {
  const startPos = headerMatch.end;
  const endPos = index < headers.length - 1 ? headers[index + 1].start : normalizedMd.length;
  const rawContent = normalizedMd.slice(startPos, endPos).trim();

  const isDescription = headerMatch.header.toLowerCase().includes('description');
  return isDescription ? rawContent.replace(/\n/g, '<br>') : rawContent;
}

function updateDataStructure(header, content, dataStructure) {
  const funcMatch = header.match(/^Functionality\s+(\d+)\s+(Name|Description)$/i);
  if (funcMatch) {
    const funcNum = parseInt(funcMatch[1], 10);
    const part = funcMatch[2];
    if (!dataStructure.functionalities[funcNum]) {
      dataStructure.functionalities[funcNum] = {};
    }
    dataStructure.functionalities[funcNum][part] = content;
  }
}

function parseMarkdownContent(markdownContent) {
  if (!markdownContent || !markdownContent.trim()) {
    throw new Error('Markdown content cannot be empty');
  }

  if (!/### Functionality \d+ Name/i.test(markdownContent)) {
    throw new Error('Release note must include at least one functionality name section (### Functionality N Name)');
  }
  if (!/### Functionality \d+ Description/i.test(markdownContent)) {
    throw new Error('Release note must include at least one functionality description section (### Functionality N Description)');
  }

  const normalizedMd = normalizeMarkdown(markdownContent);
  const headers = findSectionHeaders(normalizedMd);
  const releaseData = { functionalities: {} };

  for (let i = 0; i < headers.length; i++) {
    const content = extractSectionContent(headers[i], headers, i, normalizedMd);
    updateDataStructure(headers[i].header, content, releaseData);
  }

  if (Object.keys(releaseData.functionalities).length === 0) {
    throw new Error('Release note must include at least one functionality section');
  }

  for (const [funcKey, funcData] of Object.entries(releaseData.functionalities)) {
    if (!funcData.Name || !funcData.Name.trim()) {
      throw new Error(`Functionality ${funcKey} is missing a valid name`);
    }
    if (!funcData.Description || !funcData.Description.trim()) {
      throw new Error(`Functionality ${funcKey} is missing a valid description`);
    }
  }

  return releaseData;
}

// ---------------------------------------------------------------------------
// HTML assembly helpers – ported from zendesk_utils.py
// ---------------------------------------------------------------------------

function formatWhatsNewSection(functionalitiesData) {
  const template = (name, description) => `<ul>
      <li>
        <span class="wysiwyg-font-size-large"><strong>${name}<br></strong></span>
        <span class="wysiwyg-font-size-medium">
          ${description}
        </span>
      </li>
    </ul>
    `;

  const sorted = Object.entries(functionalitiesData.functionalities)
    .sort(([a], [b]) => Number(a) - Number(b));

  return sorted
    .filter(([, d]) => d.Name && d.Description)
    .map(([, d]) => template(d.Name, d.Description))
    .join('');
}

function formatReleaseNoteInfoStepsSection(functionalitiesData) {
  const template = (name) => `<p>
      <strong>
        <span class="wysiwyg-font-size-large">${name}</span>
      </strong>
      <span class="wysiwyg-font-size-medium"><strong><br></strong></span>
    </p>
    `;

  const sorted = Object.entries(functionalitiesData.functionalities)
    .sort(([a], [b]) => Number(a) - Number(b));

  return sorted
    .filter(([, d]) => d.Name && d.Description)
    .map(([, d]) => template(d.Name) + TEMPLATE_FEATURE_DETAILS_FOOTER)
    .join('');
}

// ---------------------------------------------------------------------------
// MCP tool definition
// ---------------------------------------------------------------------------

export const releaseNotesTools = [
  {
    name: 'create_release_note',
    description:
      'Create a Zendesk Help Center release note article from structured markdown. ' +
      'Parses "### Functionality N Name / Description" sections, assembles HTML ' +
      'using the UK or US template, and creates a draft article via the Zendesk API.',
    schema: {
      markdown_content: z.string().min(1).describe(
        'Markdown content with "### Functionality N Name" and "### Functionality N Description" sections'
      ),
      use_us_template: z.boolean().optional().default(false).describe(
        'Use the US release note template (default: false = UK template)'
      ),
      section_id: z.number().describe(
        'Zendesk Help Center section ID where the article will be created'
      ),
      title: z.string().max(256).optional().describe(
        'Custom article title. If omitted, auto-generated from feature names.'
      ),
      locale: z.string().max(10).optional().default('en-us').describe('Article locale'),
      draft: z.boolean().optional().default(true).describe('Create as draft (default: true)'),
      permission_group_id: z.number().optional().describe('Permission group ID'),
      user_segment_id: z.number().optional().describe('User segment ID'),
      author_id: z.number().optional().describe('Author user ID'),
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false },
    handler: async ({
      markdown_content,
      use_us_template = false,
      section_id,
      title,
      locale = 'en-us',
      draft = true,
      permission_group_id,
      user_segment_id,
      author_id,
    }) => {
      try {
        const releaseData = parseMarkdownContent(markdown_content);

        const featureNames = Object.entries(releaseData.functionalities)
          .sort(([a], [b]) => Number(a) - Number(b))
          .filter(([, d]) => d.Name && d.Name.trim())
          .map(([, d]) => d.Name);

        let articleTitle = title;
        if (!articleTitle) {
          const allFeatures = featureNames.join(', ');
          articleTitle = use_us_template
            ? `New Release | Main: ${allFeatures} - Labor: move features here if needed | Mmm DD YYYY`
            : `New Release | Product Name: ${allFeatures} | DD Mmm YYYY`;
          if (articleTitle.length > 256) {
            articleTitle = articleTitle.slice(0, 253) + '...';
          }
        }

        const whatsNew = formatWhatsNewSection(releaseData);
        const infoSteps = formatReleaseNoteInfoStepsSection(releaseData);

        const htmlBody = use_us_template
          ? US_TEMPLATE_HEADER + whatsNew + US_TEMPLATE_MIDDLE + infoSteps
          : UK_TEMPLATE_HEADER + whatsNew + UK_TEMPLATE_MIDDLE + infoSteps;

        const articleData = {
          title: articleTitle,
          body: htmlBody,
          locale,
          draft,
        };
        if (permission_group_id !== undefined) articleData.permission_group_id = permission_group_id;
        articleData.user_segment_id = user_segment_id !== undefined ? user_segment_id : null;
        if (author_id !== undefined) articleData.author_id = author_id;

        const result = await zendeskClient.createArticle(articleData, section_id);

        const createdArticle = result?.article || {};
        const summary = [
          `Release note created successfully!`,
          `Title: ${createdArticle.title || articleTitle}`,
          createdArticle.id ? `ID: ${createdArticle.id}` : null,
          createdArticle.html_url ? `URL: ${createdArticle.html_url}` : null,
        ].filter(Boolean).join('\n');

        return {
          content: [{ type: 'text', text: `${summary}\n\n${JSON.stringify(result, null, 2)}` }],
        };
      } catch (error) {
        return {
          content: [{ type: 'text', text: `Error creating release note: ${error.message}` }],
          isError: true,
        };
      }
    },
  },
];
