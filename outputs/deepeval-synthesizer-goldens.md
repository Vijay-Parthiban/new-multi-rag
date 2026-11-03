# DeepEval Synthesizer: which method builds the better RAG golden set here?

**Verdict:** use `generate_goldens_from_contexts()` with the chunks your ingestion service
already produced. Use `generate_goldens_from_docs()` only to cold-start a product that has
no chunks yet.

The question names the same method twice. I read it as `generate_goldens_from_docs` against
`generate_goldens_from_contexts`. Both are single-turn generators. Multi-turn has a
conversational variant of each.

Accessed: 2026-11-03. Scope: DeepEval Synthesizer docs, the synthesizer guide, and this
repository. No benchmark ran on our corpus, so the recommendation rests on the documented
pipeline and our own code.

---

## 1. What the two methods do

| | `generate_goldens_from_docs()` | `generate_goldens_from_contexts()` |
|---|---|---|
| Input | File paths | A list of contexts, each a list of strings |
| Extra step | Context construction | None |
| Extra packages | `chromadb`, `langchain-core`, `langchain-community`, `langchain-text-splitters` | None listed |
| Chunking control | `ContextConstructionConfig` (`chunk_size` 1024, `chunk_overlap` 0) | You chunk |
| Context shape | Chunks grouped by cosine similarity, quality scored | Exactly what you pass |
| Source names | `source_file` on each golden, taken from the files (inferred from the docs example) | `source_files`, one entry per context |
| Relation | Calls the contexts method under the hood | Base method |

The docs page states the relation plainly: "The only difference between the
`generate_goldens_from_docs()` and `generate_goldens_from_contexts()` method is
`generate_goldens_from_docs()` involves an additional context construction step." The
contexts FAQ repeats it and adds the rule of thumb: use the contexts method "when you
already have prepared contexts (e.g. an embedded knowledge base) and want to control
chunking yourself."

Both methods share the same generation pipeline: input generation, filtration, evolution,
expected-output generation, then styling. The docs place expected-output generation just
before styling, so styling stays last. Both produce `Golden` objects with `input`,
`expected_output`, `context`, `source_file`, and quality and evolution metadata.

## 2. Why the contexts method fits this repository

**a. We already own the chunking, and the chunk is the unit we score.**
The ingestion service stores `chunk_size`, `chunk_overlap`, and `chunk_strategy` on every
ingestion profile (`rag-ingestion-manager/backend/apps/api/routes/ingestion_profiles.py`).
The docs method re-splits the same files by default at 1024 tokens and 0 overlap. Our retrieval
metrics (`hit@k`, `recall@k`, `precision@k`, `mrr`) then grade a different text unit than
the retriever reads. The synthesizer guide warns about exactly this: chunk size "should
ideally align with the settings of the retriever in your LLM pipeline."

**b. `source_files` maps straight onto `expected_sources`.**
Our `ExpectedSource` matches a file name, with an optional `_p<page>` suffix
(`libs/eval-core/src/eval_core/source_match.py`). The contexts method takes one
`source_files` entry per context. A context built from one document therefore yields a row
whose expected source is exact. The docs method also fills `source_file`, but you cannot
choose which chunks form the group.

**c. We can group deterministically.**
The docs method selects random chunks and groups them by cosine similarity above 0.5. Our
chunks already carry source and page metadata. Grouping by file and section is repeatable,
auditable, and free.

**d. Fewer moving parts.**
The contexts method needs no ChromaDB and no LangChain splitters. The docs list no
prerequisite at all for this path, and no embedder setting, because no chunking or
grouping step runs. The docs path adds a second text pipeline that must stay in step with
ingestion.

**e. It matches the dataset we already have.**
`golden_datasets` rows are curated, file-attributed, and graded per k. Synthetic rows must
share that shape to enter the same run.

## 3. Where the docs method is still the right call

1. Cold start: a Knowledge Product exists but has no ingested chunks, or the chunker is
   known to be weak on a file type.
2. You want DeepEval to own the quality gate. The docs path scores each chunk (clarity,
   depth, structure, relevance, threshold 0.5, retries 3) and retries poor contexts. The
   contexts path skips that gate, so the caller carries it.
3. One-off exploration: you want a first small batch from a folder of PDFs without wiring a
   chunk reader.

`generate_goldens_from_goldens()` is the third useful option. It augments an existing set,
so it can grow our 10-row resume datasets without new contexts.

## 4. Recommended configuration

```python
from deepeval.synthesizer import Evolution, Synthesizer
from deepeval.synthesizer.config import EvolutionConfig, FiltrationConfig

# One context per source file: the chunks of that file, in order, capped at a few.
groups = chunks_by_source_file(kp_id, limit_chunks=4)

synthesizer = Synthesizer(
    model=judge_model,  # a DeepEvalBaseLLM wrapper around our LiteLLM proxy
    evolution_config=EvolutionConfig(
        evolutions={
            Evolution.MULTICONTEXT: 0.25,
            Evolution.CONCRETIZING: 0.25,
            Evolution.CONSTRAINED: 0.25,
            Evolution.COMPARATIVE: 0.25,
        },
        num_evolutions=1,
    ),
    filtration_config=FiltrationConfig(synthetic_input_quality_threshold=0.6),
)

goldens = synthesizer.generate_goldens_from_contexts(
    contexts=[[c.text for c in group.chunks] for group in groups],
    source_files=[group.source for group in groups],
    max_goldens_per_context=2,
    include_expected_output=True,
)
```

Notes:

1. `model` takes an OpenAI model id or a `DeepEvalBaseLLM`. Our judge runs on the LiteLLM
   proxy, so wrap it in a small `DeepEvalBaseLLM` subclass. The docs list no other way to
   reach a non-OpenAI endpoint.
2. `max_context_length` belongs to `ContextConstructionConfig` and does not apply here. The
   contexts you pass are used as they are, so cap the group yourself.
3. Keep each group to one file. Cross-file groups make `expected_sources` ambiguous.
4. `max_goldens_per_context` defaults to 2. That is a sensible first batch.
5. Goldens carry no `actual_output`. Our runner fills the answer, as it does for every row.

## 5. Mapping to our golden schema

| DeepEval field | Our column | Rule |
|---|---|---|
| `golden.input` | `question` | Keep as written |
| `golden.expected_output` | `ground_truth_answer` | Drop the row when empty |
| `golden.source_file` | `expected_sources` | One name, `[name]` |
| page number (from chunk metadata) | `expected_sources` | Append `_p<page>` when page scoring matters |
| `golden.context` | `metadata.source_contexts` | Keep for review, not for scoring |
| `additional_metadata.evolutions` | `metadata.evolutions` | Provenance |
| `additional_metadata.context_quality`, `synthetic_input_quality` | `metadata.quality` | Provenance |
| — | `metadata.source` | Set to `synthetic` |

The schema already accepts `metadata` freely
(`libs/eval-core/src/eval_core/dataset_schema.py`), so no migration is needed.

## 6. Rules that keep synthetic RAG rows valid

1. **Restrict evolutions to the four that stick to the context.** The synthesizer docs say
   that some evolutions "do not necessarily require that the evolved input can be answered
   from the context," and list `MULTICONTEXT`, `CONCRETIZING`, `CONSTRAINED`, and
   `COMPARATIVE` as the four that do. `REASONING`, `HYPOTHETICAL`, and `IN_BREADTH` can
   produce a question that the listed source cannot answer. Our `hit@k` would score that as
   a retrieval miss, which is a false signal.
2. **Generate from corpus chunks, not from retrieved chunks.** Building contexts out of the
   pipeline's own top-k makes the dataset measure self-consistency. Golden rows must be
   answerable from a source set that is independent of the retriever under test.
3. **Start with `num_evolutions=1`.** Compare one run at 1 and one at 2. Keep the setting
   that produces answerable rows with a higher hit@k.
4. **Filter before import.** Deduplicate the normalized question. Drop a row whose source
   file is no longer in the product. Drop a row with an empty expected output. Cap the
   batch.
5. **Read a sample by hand.** DeepEval states that synthetic data should be inspected and
   edited. Two goldens per context with a strict evolution mix keeps that review short.

## 7. Acceptance gate for the first batch

1. 20 to 30 rows from 10 to 15 files of one Knowledge Product.
2. Import through the existing dataset upload path. The JSONL parser accepts the converted
   rows with no warning.
3. One Offline Evaluation run completes with no row error and reports `hit@5`,
   `recall@5`, and `faithfulness`.
4. Ten random rows are answerable from their listed source.
5. The result is compared against the existing hand-made rows on the same pipeline. A large
   drop in `hit@5` points at the evolution mix or at a source mismatch, not at the pipeline.

## 8. Limits of this recommendation

1. No public benchmark compares goldens from docs against goldens from contexts on the same
   corpus. The comparison rests on the documented pipeline.
2. DeepEval's own FAQ says contexts-derived goldens "only cover what your contexts
   anticipate." Production traffic stays the better long-run source, and the Dataset
   Feedback page already covers it.
3. Quality attributes are LLM scores. A different judge model shifts them. The run should
   record the judge, as our evaluation runs already do.
4. The guide page still shows `chunk_size` and `chunk_overlap` as direct arguments of
   `generate_goldens_from_docs`. The method reference puts them in
   `ContextConstructionConfig`. Follow the method reference.
5. Image and vision chunks are out of scope. A page image cannot become a text context.
6. Multi-turn: our multi-turn rows come from real sessions. Synthetic conversation
   generation does not reproduce our session-memory behaviour, so it is not a substitute.

## Sources

1. DeepEval, "Generate Goldens From Contexts",
   https://deepeval.com/docs/synthesizer-generate-from-contexts
2. DeepEval, "Generate Goldens From Documents",
   https://deepeval.com/docs/synthesizer-generate-from-docs
3. DeepEval, "Golden Synthesizer" (pipeline, filtration, evolutions),
   https://deepeval.com/docs/golden-synthesizer
4. DeepEval, "Datasets" (goldens and test cases),
   https://deepeval.com/docs/evaluation-datasets
5. DeepEval guide, "Generate Synthetic Test Data for LLM Applications" (chunking practice,
   quality gates), https://deepeval.com/guides/guides-using-synthesizer
6. DeepEval CLI reference (`generate --method docs|contexts`),
   https://deepeval.com/docs/command-line-interface
7. DeepEval source, `synthesizer.py` (signature and delegation),
   https://github.com/confident-ai/deepeval/blob/main/deepeval/synthesizer/synthesizer.py

Repository files used: `ingestion_profiles.py`, `source_match.py`, `dataset_schema.py`
(paths in section 2).
