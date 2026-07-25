# Golden Dataset Evaluation - Implementation Requirements

Here is the complete breakdown of everything needed to fully implement the platform.

## 1. Golden Dataset Schema & Upload
*   **JSON Format**: The system must support importing Golden Datasets in the following format:
    ```json
    {
      "name": "my-eval-set",
      "items": [
        {
          "query": "What is RAG?",
          "source": [
            {
              "name": "document.pdf",
              "page": 3
            }
          ],
          "response": "RAG stands for Retrieval Augmented Generation..."
        },
        {
          "query": "What is DSA?",
          "source": [
            {
              "name": "https://geeksforgeeks.org/dsa-tutorial",
            }
          ],
          "response": "DSA stands for Data Structures and Algorithms..."
        }
      ]
    }
    ```
*   **Source Formats**: The system needs to support parsing `source` as an array of objects, containing the `name` (file / source locator) and optionally the `page` number.
*   **API**:
    *   `POST /evaluate/datasets/upload` — Multipart form upload, validates and parses JSON.
    *   `GET /evaluate/datasets` — List available datasets.
    *   `DELETE /evaluate/datasets/{dataset_id}` — Wipe a dataset and its cascade-related runs.

## 2. Evaluation Core (`eval-core`)
*   **Mathematical Stage Metrics (Retrieval & Reranking)**: Shift away from pure LLM-as-a-judge for IRS and use explicit formula-based metrics for the pipeline:
    *   *Metrics Calculation Base*: Metrics must be calculated based strictly on whether the retrieved chunk's metadata (`source_locator`, `url`, `file_name`) matches the golden dataset's source `name` (file or website URL), and whether the `page_number` matches the `page` (if provided).
    *   *Calculation Logic*:
        *   **Precision**: How many of the retrieved chunks match the expected files and pages divided by the total number of retrieved chunks.
        *   **Recall**: Whether the expected files/pages were found within the retrieved chunks.
        *   **MRR (Mean Reciprocal Rank)**: The rank position of the first chunk that matches the expected file/page.
    *   *Reranking*: Same metric calculations (`MRR delta`, `NDCG@k`, `Kendall Tau`) applied to the reranked list of chunks.
*   **LLM Metrics (Generation)**:
    *   *Faithfulness & Accuracy*: Verify the generated response strictly against the dataset's expected `response` using an LLM.

## 3. Database Layer (`rag_db`)
*   **Schema**: Ensure models exist for `GoldenDataset`, `GoldenDatasetItem`, `EvaluationRun`, and `EvaluationRunItem`.
*   **Aggregation (`aggregate_run_metrics`)**: The DB repository must store the run configuration alongside its average KPIs, grouped and weighted by their stages:
    *   `retrieval`: Averages for precision, recall, MRR, hit rates, etc.
    *   `reranker`: Averages for mrr_after, ndcg, kendall tau.
    *   `generation`: Averages for faithfulness and accuracy validations.
*   **Pagination Methods**: Add `count_runs_for_dataset` and `list_runs_for_dataset(skip, limit)` to correctly paginate evaluation runs.

## 4. RAG API (`rag-api`)
*   **Run Pagination Endpoint**:
    *   `GET /evaluate/datasets/{id}/runs?limit=X&skip=Y` -> returns `{ items, count }`.
*   **Item Drilldown Endpoint**:
    *   `GET /evaluate/runs/{id}/items` -> Returns the per-item metrics (question, expected sources, retrieval metrics, generation metrics) for the UI drill-down table.
*   **Config & Pipeline Propagation**:
    *   `POST /evaluate/runs` -> Accepts an `EvalRunConfig` linking to the user's selected Pipeline parameters. This guarantees that Golden Dataset evaluation retrieves chunks exactly like the live Chat interface for that pipeline. The configuration must include the target `collection`, `embedding_model`, `sparse_embedding_model` (for dense vs hybrid vs sparse retrieval), and `rerank` settings.

## 5. Frontend (`ingestion-frontend`)
*   **API Client (`api.ts`)**: Wire up `ragFetch` endpoints. Ensure `FormData` headers are left untouched (`Content-Type: multipart/form-data`) so file uploads succeed properly.
*   **New Route and Page**:
    *   Create a dedicated file `GoldenEvaluationsPage.tsx` exclusively for this feature.
    *   Add `/golden-evaluations` route to `App.tsx` and place a link in the main layout / navigation sidebar. Do NOT mash this together with the existing Chat Metrics UI `EvaluationsPage.tsx`.
*   **Golden Evaluation Controls (on the new page)**:
    *   Panel for Dataset Upload + List (clickable to select datasets).
    *   Panel for "New Run" featuring **Pipeline Selection**:
        *   Just like the Chat interface, fetch and display the list of Pipeline Configurations (`listPipelines()`). 
        *   When a user submits a New Run, extract the `collection`, `embedding_model`, and `sparse_embedding_model` mapped to the chosen pipeline so that the Evaluation Worker retrieves chunks exactly the way production Chat does.
        *   Additional configuration dropdowns for: Retrieval strategy (dense/sparse/hybrid), chunk limit, and reranking toggle.
    *   Panel for "Runs List", populated via `skip`/`limit` with `◀` / `▶` footer buttons displaying page indices based on `count`.
*   **Results Visualization (Click to view)**:
    *   By default, only show the "Runs List" for a dataset.
    *   **Only when a user clicks on a particular run** in the list, then display its specific KPIs and charts.
    *   Render grouped KPI cards (Retrieval, Reranker, Generation) mapping to the database aggregates (e.g. grouped precision/recall).
    *   Render a dynamic SVG Bar Chart converting `mean_*` values to graphical bars.
    *   Render a final `repo-table` showing a drill-down mapping of metrics for every single question evaluated in the run.

## 6. Required Files to Modify/Reference
To avoid reading the entire project, restrict your investigation and integration to the following key files:

*   **Chunk Metadata Structure**:
    *   `libs/shared/src/rag_shared/types.py` → Review `RetrievedChunk` which dictates the expected metadata (`source_locator`, `title`, custom metadata) returned by `vector-core`.
*   **Evaluation Core (The metrics engine)**:
    *   `libs/eval-core/src/eval_core/runner.py` → The `GoldenItemEvaluator` class orchestrating chunk retrieval and LLM validation.
    *   `libs/eval-core/src/eval_core/source_match.py` → The logic for string-matching golden dataset requirements against retrieved `chunk.metadata`.
    *   `libs/eval-core/src/eval_core/retrieval_metrics.py` & `rerank_metrics.py` → The pure calculation matrices parsing the matched results.
*   **Database & Aggregations**:
    *   `libs/database/src/rag_db/models/evaluation.py` → Database tables for datasets and run tracking.
    *   `libs/database/src/rag_db/repositories/evaluation_repository.py` → Logic for `aggregate_run_metrics` and skipping/paginating evaluations.
*   **API & Frontend**:
    *   `apps/rag-api/src/rag_api/routes/evaluate.py` → The FastAPI endpoints to intercept uploads and API configurations.
    *   `ingestion-workspace/ingestion-frontend/src/api.ts` → Contains `ragFetch` configuration that must not strip `FormData` headers.
