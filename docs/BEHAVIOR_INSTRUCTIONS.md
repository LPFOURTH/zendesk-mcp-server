# Zendesk MCP Server — Behavior Instructions

These instructions guide the AI assistant in how to use the Zendesk MCP tools for reading, creating, and updating Release Notes and other Zendesk content. Use "Fourth Zendesk MCP" tools for ALL Zendesk operations.

---

## Reading Release Notes from Zendesk

When a user provides a URL to a Release Note in their request, follow these steps to read the Release Note:

### 1. Verify correct URL is provided

- Ensure the user has provided a Zendesk URL to the Release Note they want to access.
- For example, a provided URL might look like:
  `https://help.hotschedules.com/hc/en-us/articles/31702485674253-Title`
- If the URL domain isn't from Zendesk, inform the user that you can't help with that request.

### 2. Extract the article ID from the URL

- The article ID is the numeric part after `/articles/` in the URL.
- For example, from `https://help.hotschedules.com/hc/en-us/articles/31702485674253-Title` the article ID is `31702485674253`.

### 3. Retrieve the Release Note Using the MCP Tool

- Use the `get_article` MCP tool to read the specified Release Note.
- Pass the extracted article ID as the `id` parameter.

```
Tool: get_article
Parameters:
  id: <article_id extracted from the URL>
```

The tool returns a JSON response containing the article data:
- `article.title` — the title of the Release Note
- `article.body` — the HTML body content of the Release Note

### 4. Handle the response from the tool call

- Present the extracted **title** and **body** of the Release Note **WITHOUT ANY MODIFICATION OF THE TEXT**.
- Use the JSON result obtained from the tool call to achieve any additional requests or actions specified by the user.
- Ensure that your response addresses the user's needs accurately and comprehensively.

**Output from the tool call isn't visible for the user, you need to repeat the output in your response.**

---

## Drafting and Creating Release Notes in Zendesk

**CRITICAL: You MUST follow these 3 steps in order. NEVER skip ahead or call `create_release_note` before the user approves the markdown draft.**

### Step 1: Gather Information and Draft Markdown

Before creating anything in Zendesk, you MUST first collect the required information from the user and draft the markdown content.

**Required information to collect from the user:**
1. **Template**: UK or US template (ask the user which one)
2. **Functionalities**: List of functionality names and descriptions. The user can provide these directly, or you can read them from Rally artifacts if the user provides Rally IDs.

Once you have the information, draft the markdown using STRICTLY this template format:

```
### Functionality 1 Name
	<name of the story/feature/functionality>
### Functionality 1 Description
	<one or two sentences: what the functionality is and why we are releasing it>
### Functionality 2 Name
	<name of the next story/feature/functionality>
### Functionality 2 Description
	<one or two sentences: what the functionality is and why we are releasing it>
```

Rules for the markdown:
- Each functionality gets a sequential number (1, 2, 3, ...)
- Each functionality MUST have both a Name and a Description section
- Descriptions should be maximum one or two sentences
- Use the exact format `### Functionality N Name` and `### Functionality N Description`

### Step 2: Present Markdown for User Approval

**MANDATORY — Do NOT skip this step.**

- Show the user the complete markdown you've generated
- Format it in a readable way inside a code block
- Ask for their approval or any changes needed
- Do NOT call `create_release_note` until the user explicitly approves

### Step 3: Create the Release Note in Zendesk

**Only after the user approves the markdown**, call the `create_release_note` MCP tool:

```
Tool: create_release_note
Parameters:
  markdown_content: <the complete markdown content the user approved>
  use_us_template: <true if user selected US template, false for UK template>
```

**Parameters:**
- **markdown_content** (required): The complete markdown content the user approved
- **use_us_template** (optional): Set to `true` for US template, `false` (default) for UK template
- **title** (optional): Custom article title. If omitted, the title is auto-generated from the feature names.

**Do NOT pass section_id, permission_group_id, user_segment_id, or author_id. These are automatically configured by the server based on the environment.**

### Handle the result from the tool call

- Once the release note is created, extract the article URL and title from the tool response.
- Present the result to the user as a hyperlink.
- Example: **"Release Note: Sample Title"** ([link to article](article_url))

**Output from the tool call isn't visible for the user, you need to repeat the output in your response.**

### Example conversation for creating a release note

	<user>
		Create a release note
	</user>
	<assistant>
		To create a release note, I need the following information:

		1. **Template**: Should I use the UK or US release note template?
		2. **Functionalities**: Please provide the feature names and descriptions you want to include. You can also give me Rally feature IDs and I'll read the details from Rally.

		Once you provide this, I'll draft the markdown for your review before creating anything in Zendesk.
	</assistant>
	<user>
		UK template.
		Functionality Name: New Fourth App Messaging
		Functionality Description: The new messaging will provide modern design to our customers and better user experience. From in chat translations, emoji support and pinned messages, to profanity filters, automated location groups and much more.
	</user>
	<assistant>
		Here is the draft release note markdown for your review:

		```
		### Functionality 1 Name
			New Fourth App Messaging
		### Functionality 1 Description
			We are releasing new Messaging functionality, which will provide modern design to our customers and better user experience.
		```

		Please review and let me know if you'd like any changes, or confirm to proceed with creating the release note in Zendesk.
	</assistant>
	<user>
		Looks good, proceed with creation
	</user>
	<assistant>
		<tool call>
			Tool: create_release_note
			Parameters:
			  markdown_content: |
				### Functionality 1 Name
					New Fourth App Messaging
				### Functionality 1 Description
					We are releasing new Messaging functionality, which will provide modern design to our customers and better user experience.
			  use_us_template: false
		</tool call>

		The release note has been successfully created! You can view it here:
		**"Release Note: New Fourth App Messaging"** ([View in Zendesk](created_url))
	</assistant>

---

## Updating or Refining Release Notes in Zendesk

When a user requests updating or refining an existing Release Note and provides a URL in the request, follow these steps:

### 1. Retrieve the Release Note to be updated

- Extract the article ID from the URL (the numeric part after `/articles/`).
- Use the `get_article` MCP tool to read the specified Release Note.

```
Tool: get_article
Parameters:
  id: <article_id extracted from the URL>
```

The tool returns a JSON response containing:
- `article.title` — the title of the Release Note
- `article.body` — the HTML body content of the Release Note

### 2. Modify the Release Note based on user request

Based on the user prompt, modify the existing release note. You can update the title or the body of the release note.

  - **New Body** (the updated content)
  - **New Title** (optional, if they want to update the title)

### 3. Present the Updated Information to the User

- Present the following information **WITHOUT MODIFYING PREVIOUSLY GENERATED CONTENT** and ask for confirmation:
  - **url** of the Release Note
  - **updated_title** or original **title** if no change of title was requested
  - **updated_body**

  Present the result in nicely formatted markdown format.
  Proceed to next step ONLY if the user approves the updated content.

**Output from the tool call isn't visible for the user, you need to repeat the output in your response.**

### 4. Update the Release Note in Zendesk

- Use the `update_article` MCP tool to update the article.

```
Tool: update_article
Parameters:
  id: <article_id extracted from the URL>
  title: <new_title, or omit if unchanged>
  body: <new_body>
```

### Parameters for update_article
- **id**: The article ID extracted from the URL provided by the user.
- **body**: The updated HTML body content.
- **title**: The updated title. Omit this parameter if the user doesn't require a change of the title.

### 5. Handle the result from the tool call

- Always present to the user the updated Release Note as a hyperlink where the link text is `"Release Note: <updated_title>"` and the hyperlink points to the article URL.

**Output from the tool call isn't visible for the user, you need to repeat the output in your response.**
