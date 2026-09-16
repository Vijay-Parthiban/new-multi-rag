# Prompts Management Page

## Route
`/prompts`

## Component
`PromptsPage.tsx`

## Features

CRUD interface for managing reusable LLM prompt templates.

- **Prompt Library**: Lists saved prompt templates with name, version, and usage count.
- **Template Editor**: Create/edit prompts with variable placeholders (e.g. `{context}`, `{question}`).
- **Active Prompt Selection**: Mark a prompt as active to use it in the chat pipeline.

## Backend APIs Used

- `GET /api/prompts`
- `POST /api/prompts`
- `PUT /api/prompts/{id}`
- `DELETE /api/prompts/{id}`
