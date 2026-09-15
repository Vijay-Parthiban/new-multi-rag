# Prompts Management Page

## Route
`/prompts`

## Features
Manages the prompt matrices sent to generation LLMs (`generation-core`). Defines dynamic system strings, prompt templating, and versioning used as inputs to the RAG LLM engine before chunk context is injected.

## Backend APIs Supported
- Generation config routes integrated through `POST /api/generate` metadata contexts.