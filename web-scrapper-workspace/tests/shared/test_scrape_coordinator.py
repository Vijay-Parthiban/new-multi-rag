from crawler_shared.redis.scrape_coordinator import (
    init_scrape_job,
    load_page_results,
    mark_page_finished,
    save_page_result,
    try_schedule_finalize,
)


def test_scrape_coordinator_progress() -> None:
    job_id = "test-coordinator-job"
    init_scrape_job(job_id, total_pages=2)
    save_page_result(job_id, index=0, payload={"index": 0, "success": True, "url": "https://a.com"})
    assert mark_page_finished(job_id) is False
    save_page_result(job_id, index=1, payload={"index": 1, "success": True, "url": "https://b.com"})
    assert mark_page_finished(job_id) is True
    assert try_schedule_finalize(job_id) is True
    assert try_schedule_finalize(job_id) is False
    results = load_page_results(job_id)
    assert len(results) == 2
