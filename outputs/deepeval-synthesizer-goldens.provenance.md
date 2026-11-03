# Provenance — DeepEval Synthesizer brief

Brief: `outputs/deepeval-synthesizer-goldens.md`
Research date: 2026-11-03
Method: web search, then direct reads of the primary DeepEval documentation pages and the
public source file. No secondary blog claim is used without a primary source that repeats
it.

## Claim table

| # | Claim in the brief | Source | Evidence | Confidence |
|---|---|---|---|---|
| 1 | `generate_goldens_from_docs` calls `generate_goldens_from_contexts` and differs only by context construction | 1, 2 | Contexts page: "The only difference ... is `generate_goldens_from_docs()` involves an additional context construction step" | High |
| 2 | Contexts method takes `contexts`, `include_expected_output`, `max_goldens_per_context`, `source_files`, and `source_files` length must match | 1 | Parameter list on the page | High |
| 3 | Docs method takes `document_paths` plus `context_construction_config`; supported files `.txt .docx .pdf .md .markdown .mdx` | 2 | Parameter list and FAQ | High |
| 4 | Docs method needs `chromadb`, `langchain-core`, `langchain-community`, `langchain-text-splitters` | 2 | Prerequisites block | High |
| 5 | Docs chunking defaults are 1024 tokens and 0 overlap, token splitter | 2, 3 | `ContextConstructionConfig` defaults; `TokenTextSplitter` note | High |
| 6 | Context construction = parse, select random chunks with LLM quality score, group by cosine similarity | 2 | "How Does Context Construction Work?" | High |
| 7 | Quality threshold 0.5, similarity threshold 0.5, 3 retries | 2, 5 | `context_quality_threshold`, `context_similarity_threshold`, `max_retries`; guide restates 0.5 / 3 | High |
| 8 | Shared pipeline: input generation, filtration, evolution, expected output, styling | 3 | "How Does it Work?" plus the note that expected output runs before styling | High |
| 9 | Only `MULTICONTEXT`, `CONCRETIZING`, `CONSTRAINED`, `COMPARATIVE` stick to the context | 3 | RAG callout in the Evolution section | High |
| 10 | Golden carries `input`, `expected_output`, `context`, `source_file`, and quality/evolution metadata | 3 | `to_pandas` table and `additional_metadata` examples | High |
| 11 | Synthesizer does not generate `actual_output` | 3 | Note in Golden Synthesizer | High |
| 12 | Use the contexts method when contexts are prepared and chunking is controlled by the caller | 1 | FAQ answer on the contexts page | High |
| 13 | Chunk size should align with the retriever settings | 5 | Best practice 1 under Document Chunking | High |
| 14 | Synthetic data should be inspected and edited by hand | 3 | "Should you generate synthetic datasets?" | High |
| 15 | Contexts-derived goldens only cover what the contexts anticipate | 1 | FAQ: "Are goldens generated from contexts enough once my app is live?" | High |
| 16 | CLI supports `--method docs` and `--method contexts` | 6 | CLI `generate` section | High |
| 17 | `source_files`, `context_chunk_source_files`, `target_files_per_context` exist in the source signature | 7 | `generate_goldens_from_contexts` signature | Medium — the docs list only `source_files` |
| 18 | Ingestion chunking is per profile (`chunk_size`, `chunk_overlap`, `chunk_strategy`) | Repo: `rag-ingestion-manager/backend/apps/api/routes/ingestion_profiles.py` | Fields on the profile model | High (code read) |
| 19 | `expected_sources` accepts a file name and an optional `_p<page>` suffix | Repo: `libs/eval-core/src/eval_core/source_match.py` | Docstring and parser | High (code read) |
| 20 | Dataset rows accept free `metadata` | Repo: `libs/eval-core/src/eval_core/dataset_schema.py` | Schema field | High (code read) |

## Queries run

1. "DeepEval Synthesizer generate_goldens_from_contexts documentation"
2. "DeepEval generate_goldens_from_docs vs generate_goldens_from_contexts difference"
3. "DeepEval synthesizer synthesizer.generate_goldens_from_docs context construction chunking"
4. "DeepEval golden dataset generation RAG best practice evolution types"

## Not verified

1. No measurement of golden quality for our corpus. The brief's acceptance gate is the
   substitute.
2. The exact DeepEval release that introduced `context_chunk_source_files` and
   `target_files_per_context`.
3. Cost per generated golden. The brief gives no number, because the docs give none.
4. Whether `Evolution` accepts a partial distribution in the installed version. The code
   sketch assumes the documented behaviour.
5. A direct comparison against RAGAS testset generation was not run, so the brief makes no
   claim about it.

## Changes between sources

The contexts page still dates from 2025-03-10 and lists four parameters. The `synthesizer.py`
source exposes more. The brief follows the documented four and flags the extra parameters
as unverified.

## Verification round

An independent verifier read the four primary pages and compared them with the brief. It
returned one wrong claim and four unsupported phrasings. All five are corrected in the
brief.

| Finding | Correction in the brief |
|---|---|
| The pipeline order was wrong: expected-output generation runs before styling, not after | Section 1 now reads input, filtration, evolution, expected output, styling |
| "None (no embedder either)" is not stated for the contexts path | The cell now reads "None listed" |
| The docs path does not state that `source_file` is derived from the files | The cell marks it as inferred from the docs example DataFrame |
| "20 rows in five minutes" has no source | Removed |
| `OPENAI_BASE_URL` has no source | Removed. The brief now says the proxy needs a `DeepEvalBaseLLM` wrapper |

Two source conflicts are now recorded in the brief (limit 4) and here:

1. The guide shows `chunk_size` and `chunk_overlap` as direct arguments of
   `generate_goldens_from_docs`. The method reference places both in
   `ContextConstructionConfig`. The brief follows the method reference.
2. The docs page gives the total as `max_goldens_per_context` times
   `max_contexts_per_document`. The contexts page says each context yields up to
   `max_goldens_per_context`. Both are true for their own path. The brief states the
   contexts-path rule, because that is the recommended path here.

## Confidence summary

| Claim group | Confidence | Basis |
|---|---|---|
| What each method does and how they relate | High | Two pages state the delegation in the same words |
| Parameter names and defaults | High | Method reference lists them |
| Context construction behaviour | High | Method reference describes the three steps and their thresholds |
| Evolution types that stick to context | High | Direct callout on the synthesizer page |
| Golden fields | High | Example DataFrame and metadata examples |
| Fit for this repository | Medium | Derived from our code plus the documented chunking advice. No measurement |
| Acceptance gate | Medium | A proposal. No run has used it yet |
