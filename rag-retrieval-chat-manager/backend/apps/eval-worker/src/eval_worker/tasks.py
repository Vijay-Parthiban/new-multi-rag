from __future__ import annotations

import logging
import random
import uuid

from eval_core.chat_metrics import compute_chat_pipeline_metrics, flatten_chat_metrics
from eval_core.runner import GoldenItem, GoldenItemEvaluator
from rag_core import DEFAULT_TTL_S, PipelineConfig, SessionMemory
from rag_db.repositories.chat_repository import ChatRepository
from rag_db.repositories.evaluation_repository import EvaluationRepository
from rag_db.services.database import get_session_factory
from rag_shared.config import get_settings
from rag_shared.types import KpStores, SearchMode

logger = logging.getLogger(__name__)


def _dump_chunks(chunks: list) -> list[dict]:
    """The chunks as plain dicts, with the image payload left out.

    A page-image chunk carries its page PNG so the vision model can read it. A
    stored row keeps the page text: the bytes would add megabytes to a run's rows
    and to every response that reads them.
    """
    dumped: list[dict] = []
    for chunk in chunks or []:
        record = chunk.model_dump()
        metadata = dict(record.get("metadata") or {})
        metadata.pop("image_base64", None)
        metadata.pop("image", None)
        record["metadata"] = metadata
        dumped.append(record)
    return dumped


def emit_otel_synthetic_trace(
    session_id: str,
    message_id: str,
    query: str,
    answer: str,
    latency_ms: dict,
    scores: dict,
    retrieved_chunks: list,
    trace_info: dict,
    trace_mode: str = "prod",
    parent: tuple[str, str] | None = None,
) -> None:
    from rag_shared.tracing import emit_rag_pipeline_trace

    emit_rag_pipeline_trace(
        session_id=session_id,
        message_id=message_id,
        query=query,
        answer=answer,
        latency_ms=latency_ms,
        scores=scores,
        retrieved_chunks=retrieved_chunks,
        trace_info=trace_info,
        flush=True,
        trace_mode=trace_mode,
        # The turn's own trace id and span id. Without them this opens a second trace and the
        # same question shows up twice in Langfuse and Phoenix.
        parent=parent,
    )


def compute_chat_metrics(message_id: str) -> None:
    settings = get_settings()
    session_factory = get_session_factory(settings)
    msg_uuid = uuid.UUID(message_id)

    with session_factory() as db:
        chat_repo = ChatRepository(db)
        db_trace = chat_repo.get_trace_for_message(msg_uuid)
        message = chat_repo.get_message(msg_uuid)
        if not db_trace or not message:
            chat_repo.update_metrics(msg_uuid, scores={}, status="failed", error_message="Trace not found")
            db.commit()
            return
            
        try:
            parsed_latency = db_trace.latency_ms or {}
            staged = compute_chat_pipeline_metrics(
                settings,
                question=db_trace.query,
                answer=message.content,
                retrieved_chunks=db_trace.retrieved_chunks or [],
                reranked_chunks=db_trace.reranked_chunks or [],
            )
            scores = flatten_chat_metrics(staged)
            chat_repo.update_metrics(msg_uuid, scores=scores, status="completed")
            trace_info = {
                "retrieval_mode": db_trace.retrieval_mode,
                "rerank_enabled": db_trace.rerank_enabled,
                "generation_model": db_trace.generation_model,
                "prompt_tokens": parsed_latency.pop("prompt_tokens", None),
                "completion_tokens": parsed_latency.pop("completion_tokens", None),
            }
            
            emit_otel_synthetic_trace(
                session_id=str(message.session_id),
                message_id=str(message.id),
                query=db_trace.query,
                answer=message.content,
                latency_ms=parsed_latency,
                scores=scores,
                retrieved_chunks=db_trace.retrieved_chunks or [],
                trace_info=trace_info,
                trace_mode=db_trace.trace_mode or "prod",
                parent=(
                    (db_trace.otel_trace_id, db_trace.otel_span_id)
                    if db_trace.otel_trace_id and db_trace.otel_span_id
                    else None
                ),
            )
            
        except Exception as exc:
            logger.exception("compute_chat_metrics failed: %s", exc)
            chat_repo.update_metrics(
                msg_uuid, scores={}, status="failed", error_message=str(exc)
            )
        db.commit()


def _sample(items: list[dict], size: object, seed: object) -> list[dict]:
    """A random sample of at most `size` items.

    No size, a size of zero, or a size past the end of the set means the whole set: a run that
    asks for more rows than exist should evaluate all of them rather than fail.

    `random.Random` with an integer seed reproduces the same sample, which is what makes a run
    repeatable. With no seed it draws a fresh one, which is what a spot check wants.
    """
    if not isinstance(size, int) or size <= 0 or size >= len(items):
        return items
    return random.Random(seed if isinstance(seed, int) else None).sample(items, size)


def run_evaluation(run_id: str) -> None:
    settings = get_settings()
    session_factory = get_session_factory(settings)
    run_uuid = uuid.UUID(run_id)
    evaluator = GoldenItemEvaluator(settings)

    with session_factory() as db:
        eval_repo = EvaluationRepository(db)
        run = eval_repo.get_run(run_uuid)
        if not run:
            return
        config_data = dict(run.config or {})
        dataset_id = run.dataset_id
        eval_repo.mark_run_running(run_uuid)
        db.commit()

    # An assistant pipeline reads its Knowledge Product's stores. The strategy and the store
    # names travel together: with a strategy the pipeline reads those stores, and without one
    # it reads the legacy scrape collection, which is a different corpus.
    kp_strategy = config_data.get("rag_strategy")
    kp_stores = None
    if kp_strategy and (config_data.get("collection") or config_data.get("opensearch_index")):
        kp_stores = KpStores(
            qdrant_collection=config_data.get("collection"),
            opensearch_index=config_data.get("opensearch_index"),
            pg_schema=config_data.get("pg_schema"),
            pg_table=config_data.get("pg_table"),
        )

    config = PipelineConfig(
        retrieval_mode=SearchMode(config_data.get("retrieval_mode", "hybrid")),
        retrieve_limit=config_data.get("retrieve_limit", settings.retrieve_limit),
        rerank_enabled=config_data.get("rerank_enabled", settings.reranker_enabled),
        rerank_model=config_data.get("rerank_model"),
        top_k=config_data.get("top_k", settings.rerank_top_k),
        generation_model=config_data.get("generation_model"),
        # The page-image strategy answers from the images, so for it the run's
        # generation model is also its vision model. Without this the deployment's
        # vision model answers instead, which is not the model the pipeline named.
        vision_model=(
            config_data.get("generation_model")
            if config_data.get("rag_strategy") == "image_vision"
            else None
        ),
        collection=config_data.get("collection"),
        embedding_model=config_data.get("embedding_model"),
        sparse_embedding_model=config_data.get("sparse_embedding_model"),
        # The strategy picks the store the run reads and, for self_rag and corrective, the
        # grading and revision the pipeline performs on what that store returned.
        strategy=kp_strategy,
        stores=kp_stores,
    )

    # The pipeline's own session memory, resolved from the run config. Absent for a
    # single-turn run and for a pipeline whose Knowledge Product has no Redis destination.
    session_memory = None
    if config_data.get("session_memory_prefix"):
        session_memory = SessionMemory(
            settings,
            prefix=config_data["session_memory_prefix"],
            ttl_s=config_data.get("session_memory_ttl_s") or DEFAULT_TTL_S,
        )

    k_values = config_data.get("k_values", [1, 3, 5, 10])

    with session_factory() as db:
        eval_repo = EvaluationRepository(db)
        raw_items = eval_repo.list_dataset_items(dataset_id)
        dataset_items = [
            {
                "id": item.id,
                "question": item.question,
                "ground_truth_answer": item.ground_truth_answer or "",
                "expected_sources": item.expected_sources or [],
                "turns": item.turns or None,
                "metadata": item.metadata_ or {},
            }
            for item in raw_items
        ]

    # A run may evaluate a random sample instead of the whole set. This happens before the
    # progress count is taken, so the count describes what will actually run.
    dataset_items = _sample(
        dataset_items, config_data.get("sample_size"), config_data.get("seed")
    )

    total_items = len(dataset_items)
    logger.info("Starting evaluation run=%s dataset_items=%d", run_uuid, total_items)

    try:
        for index, item in enumerate(dataset_items, start=1):
            run_item_id: uuid.UUID | None = None
            try:
                with session_factory() as db:
                    eval_repo = EvaluationRepository(db)
                    run_item = eval_repo.create_run_item(run_uuid, item["id"])
                    db.commit()
                    run_item_id = run_item.id

                logger.info(
                    "Evaluating run=%s query %d/%d item_id=%s",
                    run_uuid,
                    index,
                    total_items,
                    item["id"],
                )

                golden = GoldenItem(
                    question=item["question"],
                    ground_truth_answer=item["ground_truth_answer"],
                    expected_sources=item["expected_sources"],
                    label=item["metadata"].get("label"),
                    category=item["metadata"].get("category"),
                    turns=item["turns"],
                    metadata=item["metadata"],
                )
                result = evaluator.evaluate_item(
                    golden,
                    config,
                    k_values,
                    judge_model=config_data.get("judge_model"),
                    session_memory=session_memory,
                )

                with session_factory() as db:
                    eval_repo = EvaluationRepository(db)
                    eval_repo.save_run_item_result(
                        run_item_id,
                        retrieved_chunks=_dump_chunks(result.retrieved_chunks),
                        retrieval_metrics=result.retrieval_metrics,
                        reranked_chunks=_dump_chunks(result.reranked_chunks),
                        rerank_metrics=result.rerank_metrics,
                        generated_answer=result.generated_answer,
                        generation_metrics=result.generation_metrics,
                        generated_turns=result.generated_turns,
                    )
                    progress = eval_repo.get_run_progress(run_uuid)
                    db.commit()
                    
                    # Combine all metrics for OTel tracing
                    combined_scores = {}
                    if result.retrieval_metrics:
                        combined_scores.update(result.retrieval_metrics)
                    if result.rerank_metrics:
                        combined_scores.update(result.rerank_metrics)
                    if result.generation_metrics:
                        combined_scores.update(result.generation_metrics)

                    # The evaluator does not time its stages, so EvalItemResult carries no
                    # latency. Reading it directly raised on every item, which meant no result
                    # was ever saved even when the evaluation itself succeeded.
                    latency_ms = getattr(result, "latency_ms", None) or {}
                    trace_info = {
                        "retrieval_mode": config.retrieval_mode.value,
                        "rerank_enabled": config.rerank_enabled,
                        "generation_model": config.generation_model,
                        "route": (result.generation_metrics or {}).get("route", "normal"),
                        "prompt_tokens": latency_ms.get("prompt_tokens"),
                        "completion_tokens": latency_ms.get("completion_tokens"),
                    }

                    emit_otel_synthetic_trace(
                        session_id=f"eval_run_{run_uuid}",
                        message_id=str(run_item_id),
                        query=item["question"],
                        answer=result.generated_answer,
                        latency_ms=latency_ms,
                        scores=combined_scores,
                        retrieved_chunks=_dump_chunks(result.retrieved_chunks),
                        trace_info=trace_info
                    )

                    logger.info(
                        "Completed run=%s progress %d/%d (failed=%d)",
                        run_uuid,
                        progress["items_completed"],
                        progress["items_total"],
                        progress["items_failed"],
                    )
            except Exception as exc:
                logger.exception("Eval item failed run=%s query %d/%d", run_uuid, index, total_items)
                if run_item_id:
                    with session_factory() as db:
                        eval_repo = EvaluationRepository(db)
                        eval_repo.fail_run_item(run_item_id, str(exc))
                        db.commit()

        with session_factory() as db:
            eval_repo = EvaluationRepository(db)
            aggregate = eval_repo.aggregate_run_metrics(run_uuid)
            eval_repo.mark_run_completed(run_uuid, aggregate)
            db.commit()
            logger.info("Evaluation run=%s finished aggregate_keys=%d", run_uuid, len(aggregate))
    except Exception as exc:
        with session_factory() as db:
            eval_repo = EvaluationRepository(db)
            eval_repo.mark_run_failed(run_uuid, str(exc))
            db.commit()
        raise


def run_synthesis(version_id: str, kinds: list[str] | None = None) -> None:
    """Generate one or both datasets of a version.

    Each kind is one `golden_datasets` row with its own configuration, its own row count
    and its own object. A kind is reset before it runs, so a re-delivered job or a
    Regenerate click cannot append a second set of rows. One kind failing marks only that
    kind failed; the other still runs and keeps its rows.
    """
    import asyncio
    import json
    from datetime import UTC, datetime

    from sqlalchemy import text

    from eval_core.synthesis_constants import KIND_CONFIG_KEY
    from rag_db.repositories.synthetic_dataset_repository import SyntheticDatasetRepository

    def now() -> datetime:
        return datetime.now(UTC)

    settings = get_settings()
    session_factory = get_session_factory(settings)
    version_uuid = uuid.UUID(version_id)

    with session_factory() as db:
        repo = SyntheticDatasetRepository(db)
        eval_repo = EvaluationRepository(db)
        version = repo.get_version(version_uuid)
        if not version:
            logger.warning("synthesis version not found id=%s", version_id)
            return
        profile = repo.get_profile(version.profile_id)
        if not profile:
            logger.warning("synthesis profile missing version=%s", version_id)
            return

        stored = dict(version.config or {})
        model_name = str(stored.get("model") or "")
        datasets = {dataset.kind: dataset for dataset in repo.datasets_for_version(version_uuid)}
        selected = [kind for kind in (kinds or list(datasets)) if kind in datasets]
        if not selected:
            logger.warning("synthesis version=%s has no dataset to generate", version_id)
            return

        progress = dict(version.progress or {})
        kind_progress: dict[str, dict] = {
            kind: dict((progress.get("kinds") or {}).get(kind) or {}) for kind in datasets
        }

        def save_progress() -> None:
            # The two kinds can be two jobs on two workers, so merge this job's kinds into
            # the stored progress instead of writing a snapshot over the other job's.
            db.execute(
                text(
                    "update synthetic_dataset_versions "
                    "set progress = jsonb_set(coalesce(progress, '{}'::jsonb), '{kinds}', "
                    "coalesce(progress->'kinds', '{}'::jsonb) || cast(:kinds as jsonb)) "
                    "where id = :id"
                ),
                {
                    "kinds": json.dumps({kind: kind_progress[kind] for kind in selected}),
                    "id": str(version_uuid),
                },
            )
            db.commit()

        repo.update_version(
            version_uuid,
            status="running",
            # The second job of a version must not reset the shared start time.
            started_at=version.started_at or now(),
            error_message=None,
            completed_at=None,
        )
        for kind in selected:
            kind_progress[kind].update(
                status="running", phase="reading_chunks", rows=0, skipped=0, error=None
            )
        save_progress()

        def callback_for(kind: str):
            dataset = datasets[kind]
            written = 0

            def callback(rows: list[dict], total: int, index: int) -> None:
                nonlocal written
                for row in rows[written:]:
                    eval_repo.add_dataset_item(dataset.id, **row)
                written = len(rows)
                dataset.row_count = written
                kind_progress[kind].update(
                    contexts_total=total,
                    contexts_done=index + 1,
                    rows=written,
                )
                save_progress()

            return callback

        def generate(kind: str) -> None:
            from eval_core.dataset_schema import dataset_items_to_jsonl
            from eval_core.dataset_storage import versioned_key, put_dataset, resolve_bucket
            from eval_core.synthesis import (
                LiteLlmModel,
                SynthesisError,
                build_contexts,
                build_synthesizer,
                chunks_for_product,
                synthesize_multi,
                synthesize_single,
            )

            cfg = dict(stored.get(KIND_CONFIG_KEY[kind]) or {})
            target = int(cfg.get("rows") or 0)
            if target < 1:
                raise SynthesisError("This dataset has no row count. Set one and run it again.")

            dataset = datasets[kind]
            repo.clear_dataset_items(dataset.id)
            dataset.row_count = 0
            dataset.storage_bucket = None
            dataset.storage_key = None
            dataset.source_format = None
            kind_progress[kind].update(
                status="running",
                phase="reading_chunks",
                rows=0,
                rows_target=target,
                skipped=0,
                warning=None,
                error=None,
            )
            save_progress()

            chunks = cached_chunks()
            groups = build_contexts(
                chunks, chunks_per_context=int(cfg.get("chunks_per_context") or 4)
            )
            if not groups:
                raise SynthesisError(
                    "No text chunks in this Knowledge Product's Qdrant collection."
                )
            kind_progress[kind].update(contexts_total=len(groups), contexts_done=0)
            save_progress()

            synth = build_synthesizer({**cfg, "model": model_name}, model)
            per_context = int(cfg.get("max_goldens_per_context") or 2)

            if kind == "single_turn":
                kind_progress[kind]["phase"] = "generating_single"
                rows = synthesize_single(
                    synth,
                    groups,
                    needed=target,
                    per_context=per_context,
                    model=model_name,
                    profile_id=str(profile.id),
                    version_id=str(version_uuid),
                    on_progress=callback_for(kind),
                )
            else:
                kind_progress[kind]["phase"] = "generating_multi"
                rows, skipped = synthesize_multi(
                    synth,
                    groups,
                    needed=target,
                    turns=int(cfg.get("turns") or 2),
                    per_context=per_context,
                    model=model,
                    profile_id=str(profile.id),
                    version_id=str(version_uuid),
                    on_progress=callback_for(kind),
                )
                kind_progress[kind]["skipped"] = skipped

            if len(rows) < target:
                kind_progress[kind]["warning"] = "contexts exhausted"

            kind_progress[kind]["phase"] = "saving"
            save_progress()

            if rows:
                items = [
                    {
                        "question": item.question,
                        "ground_truth_answer": item.ground_truth_answer,
                        "expected_sources": item.expected_sources or [],
                        "turns": item.turns,
                        "metadata": item.metadata_ or {},
                    }
                    for item in eval_repo.list_dataset_items(dataset.id)
                ]
                filename = f"v{version.version_no}.jsonl"
                key = versioned_key(
                    profile.knowledge_product_id, str(profile.id), version.version_no, kind, filename
                )
                bucket = resolve_bucket(settings)
                asyncio.run(
                    put_dataset(
                        settings,
                        bucket=bucket,
                        key=key,
                        data=dataset_items_to_jsonl(items),
                        filename=filename,
                    )
                )
                dataset.storage_bucket = bucket
                dataset.storage_key = key
                dataset.source_format = "jsonl"

            kind_progress[kind].update(status="completed", phase="done", rows=len(rows))
            save_progress()

        def cached_chunks() -> list[dict]:
            from eval_core.synthesis import chunks_for_product

            if "chunks" not in cache:
                cache["chunks"] = chunks_for_product(
                    settings,
                    collection=profile.qdrant_collection,
                    knowledge_product_id=profile.knowledge_product_id,
                    limit=5000,
                )
            return cache["chunks"]

        cache: dict[str, list[dict]] = {}

        try:
            from eval_core.synthesis import LiteLlmModel

            model = LiteLlmModel(model_name, settings.litellm_base_url, settings.openai_api_key)
        except Exception as exc:
            logger.exception("synthesis could not build the model version=%s", version_id)
            for kind in selected:
                kind_progress[kind].update(status="failed", error=str(exc)[:500])
            repo.update_version(
                version_uuid,
                status="failed",
                error_message=str(exc)[:1000],
                completed_at=now(),
            )
            save_progress()
            return

        for kind in selected:
            try:
                generate(kind)
            except Exception as exc:
                logger.exception("synthesis failed version=%s kind=%s", version_id, kind)
                db.rollback()
                kind_progress[kind].update(status="failed", error=str(exc)[:500])
                save_progress()

        failures = [kind for kind in selected if kind_progress[kind].get("status") == "failed"]
        message = "; ".join(
            f"{kind}: {kind_progress[kind].get('error')}" for kind in failures
        )[:1000]
        # The other kind can still be running as its own job, so the version only closes
        # when every kind has stopped. Read the stored progress, not this job's snapshot.
        save_progress()
        db.expire_all()
        stored = repo.get_version(version_uuid)
        stored_kinds = ((stored.progress if stored else None) or {}).get("kinds") or {}
        others_running = any(
            (state or {}).get("status") in ("queued", "running")
            for kind, state in stored_kinds.items()
            if kind not in selected
        )
        counted = {
            dataset.kind: dataset.row_count or 0
            for dataset in repo.datasets_for_version(version_uuid)
        }
        repo.update_version(
            version_uuid,
            status="running" if others_running else ("failed" if failures else "completed"),
            error_message=message or None,
            completed_at=None if others_running else now(),
            row_count_single=counted.get("single_turn", 0),
            row_count_multi=counted.get("multi_turn", 0),
        )
        save_progress()
        logger.info(
            "synthesis version=%s finished kinds=%s rows=%s",
            version_id,
            ",".join(selected),
            {kind: kind_progress[kind].get("rows") for kind in selected},
        )
