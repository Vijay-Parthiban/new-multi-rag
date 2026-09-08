from unittest.mock import AsyncMock, MagicMock, patch

from eval_core.chat_metrics import compute_chat_pipeline_metrics, flatten_chat_metrics


@patch("eval_core.chat_metrics.calculate_generation_ragas_async", new_callable=AsyncMock)
@patch("eval_core.chat_metrics.calculate_retrieval_ragas_async", new_callable=AsyncMock)
@patch("eval_core.chat_metrics.kendall_tau_rank_correlation")
def test_compute_chat_pipeline_metrics_splits_stages(
    mock_tau,
    mock_retrieval,
    mock_faith,
) -> None:
    mock_retrieval.return_value = {"context_precision": 0.8, "context_recall": 0.7}
    mock_faith.return_value = {"faithfulness": 0.9}
    mock_tau.return_value = 0.42

    settings = MagicMock()
    settings.ragas_enabled = True

    staged = compute_chat_pipeline_metrics(
        settings,
        question="What is HTML?",
        answer="HTML is markup.",
        retrieved_chunks=[
            {
                "id": "1",
                "content": "HTML docs",
                "source_type": "web_scrape",
                "source_id": "j1",
                "source_locator": "https://example.com",
                "chunk_index": 0,
                "chunk_type": "text",
                "retrieval_score": 0.9,
            }
        ],
        reranked_chunks=[
            {
                "id": "1",
                "content": "HTML docs",
                "source_type": "web_scrape",
                "source_id": "j1",
                "source_locator": "https://example.com",
                "chunk_index": 0,
                "chunk_type": "text",
                "retrieval_score": 0.9,
                "rerank_score": 0.95,
            }
        ],
    )

    assert staged["retrieval"]["context_precision"] == 0.8
    assert staged["generation"]["faithfulness"] == 0.9
    assert staged["reranker"]["kendall_tau"] == 0.42

    flat = flatten_chat_metrics(staged)
    assert flat["context_precision"] == 0.8
    assert flat["faithfulness"] == 0.9
    assert flat["kendall_tau"] == 0.42
    assert flat["raw_ragas"]["generation"]["faithfulness"] == 0.9
