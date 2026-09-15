# Overview / Dashboard Page

## Route
`/` (default route)

## Component
`HomePage.tsx`

## Features
Displays high-level operational statistics and access cards for the workspace:
- **Metrics Bar**: Shows aggregated counts for Connected Data Sources, Workspace Folders, Ingested Files, and Knowledge Profiles.
- **Section Cards**: Quick navigation entry points to `Sources`, `Folders & Files`, `External Connectors`, and `Knowledge Store Fanout`.
- Designed as a static launching pad pointing users to the actual management domains (e.g. `source-*, pipelines`).

*Note: There are no specific backend API routes for this page alone, it aggregates metadata likely fetched downstream by individual page components.*