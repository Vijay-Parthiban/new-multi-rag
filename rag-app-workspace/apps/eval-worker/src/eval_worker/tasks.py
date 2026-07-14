from __future__ import annotations

import logging
import uuid

from eval_core.chat_metrics import compute_chat_pipeline_metrics, flatten_chat_metrics
from eval_core.runner import GoldenItem, GoldenItemEvaluator
from rag_core import PipelineConfig
from rag_db.repositories.chat_repository import ChatRepository
from rag_db.repositories.evaluation_repository import EvaluationRepository
from rag_db.services.database import get_session_factory
from rag_shared.config import get_settings
from rag_shared.types import SearchMode

logger = logging.getLogger(__name__)


def compute_chat_metrics(message_id: str) -> None:
    settings = get_settings()
    session_factory = get_session_factory(settings)
    msg_uuid = uuid.UUID(message_id)

    with session_factory() as db:
        chat_repo = ChatRepository(db)
        trace = chat_repo.get_trace_for_message(msg_uuid)
        message = chat_repo.get_message(msg_uuid)
        if not trace or not message:
            chat_repo.update_metrics(msg_uuid, scores={}, status="failed", error_message="Trace not found")
            db.commit()
            return

        try:
            staged = compute_chat_pipeline_metrics(
                settings,
                question=trace.query,
                answer=message.content,
                retrieved_chunks=trace.retrieved_chunks or [],
                reranked_chunks=trace.reranked_chunks or [],
            )
            scores = flatten_chat_metrics(staged)
            chat_repo.update_metrics(msg_uuid, scores=scores, status="completed")
        except Exception as exc:
            logger.exception("compute_chat_metrics failed: %s", exc)
            chat_repo.update_metrics(
                msg_uuid, scores={}, status="failed", error_message=str(exc)
            )
        db.commit()


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

    config = PipelineConfig(
        retrieval_mode=SearchMode(config_data.get("retrieval_mode", "hybrid")),
        retrieve_limit=config_data.get("retrieve_limit", settings.retrieve_limit),
        rerank_enabled=config_data.get("rerank_enabled", settings.reranker_enabled),
        rerank_model=config_data.get("rerank_model"),
        top_k=config_data.get("top_k", settings.rerank_top_k),
        generation_model=config_data.get("generation_model"),
        collection=config_data.get("collection"),
        embedding_model=config_data.get("embedding_model"),
        sparse_embedding_model=config_data.get("sparse_embedding_model"),
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
                "metadata": item.metadata_ or {},
            }
            for item in raw_items
        ]

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
                )
                result = evaluator.evaluate_item(golden, config, k_values)

                with session_factory() as db:
                    eval_repo = EvaluationRepository(db)
                    eval_repo.save_run_item_result(
                        run_item_id,
                        retrieved_chunks=[c.model_dump() for c in result.retrieved_chunks],
                        retrieval_metrics=result.retrieval_metrics,
                        reranked_chunks=[c.model_dump() for c in result.reranked_chunks],
                        rerank_metrics=result.rerank_metrics,
                        generated_answer=result.generated_answer,
                        generation_metrics=result.generation_metrics,
                    )
                    progress = eval_repo.get_run_progress(run_uuid)
                    db.commit()
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
