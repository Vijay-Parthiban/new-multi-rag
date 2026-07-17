import logging
import shutil
import uuid
from pathlib import Path
from typing import Literal

import typer

from crawler_db.services.crawl_service import CrawlService, ScrapeService
from crawler_db.session import session_scope
from crawler_shared.config import get_settings
from crawler_shared.logging_config import setup_logging
from crawler_shared.redis.queue import enqueue_crawl, enqueue_scrape
from platform_common.ssrf import UnsafeURLError, validate_public_http_url

setup_logging()
logger = logging.getLogger(__name__)

app = typer.Typer(help="Web crawler CLI")


def _format_job(job) -> str:
    lines = [
        f"ID: {job.id}",
        f"Status: {job.status.value}",
        f"Seed URL: {job.seed_url}",
        f"Max depth: {job.max_depth}",
        f"Max pages: {job.max_pages}",
        f"Mode: {getattr(job, 'crawl_mode', 'httpx')}",
        f"Created: {job.created_at}",
    ]
    if job.started_at:
        lines.append(f"Started: {job.started_at}")
    if job.finished_at:
        lines.append(f"Finished: {job.finished_at}")
    if job.error_message:
        lines.append(f"Error: {job.error_message}")
    if getattr(job, "result", None):
        result = job.result
        lines.extend(
            [
                f"Links file: {result.links_file_path}",
                f"Total links: {result.total_links}",
                f"Pages crawled: {result.pages_crawled}",
            ]
        )
    return "\n".join(lines)


@app.command("crawl")
def crawl(
    url: str = typer.Argument(..., help="Seed URL to crawl"),
    max_depth: int = typer.Option(2, "--max-depth", min=0),
    max_pages: int = typer.Option(50, "--max-pages", min=1),
    mode: Literal["httpx", "playwright", "auto"] = typer.Option("httpx", "--mode"),
) -> None:
    """Create a crawl job and enqueue it."""
    settings = get_settings()
    try:
        url = validate_public_http_url(url, allow_private=settings.allow_private_crawl_urls)
    except UnsafeURLError as exc:
        typer.echo(f"Unsafe seed URL: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    service = CrawlService()
    with session_scope() as session:
        job = service.create_crawl_job(
            session,
            seed_url=url,
            max_depth=max_depth,
            max_pages=max_pages,
            crawl_mode=mode,
        )
        job_id = job.id
    enqueue_crawl(job_id)
    logger.info("cli_crawl_enqueued id=%s seed_url=%s mode=%s", job_id, url, mode)
    typer.echo(f"Crawl job created: {job_id}")


@app.command("status")
def status(job_id: str = typer.Argument(..., help="Crawl job UUID")) -> None:
    """Show crawl job status."""
    service = CrawlService()
    with session_scope() as session:
        job = service.get_job(session, uuid.UUID(job_id))
    if job is None:
        typer.echo(f"Job not found: {job_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(_format_job(job))


@app.command("list")
def list_jobs(limit: int = typer.Option(20, "--limit", min=1)) -> None:
    """List recent crawl jobs."""
    service = CrawlService()
    with session_scope() as session:
        jobs = service.list_jobs(session, limit=limit)
    if not jobs:
        typer.echo("No crawl jobs found.")
        return
    for job in jobs:
        typer.echo(f"{job.id}  {job.status.value}  {job.seed_url}")


@app.command("links")
def links(
    job_id: str = typer.Argument(..., help="Crawl job UUID"),
    output: Path | None = typer.Option(None, "--output", help="Copy links file to this path"),
) -> None:
    """Print or export the links file for a completed crawl."""
    service = CrawlService()
    with session_scope() as session:
        job = service.get_job(session, uuid.UUID(job_id))
    if job is None or job.result is None:
        typer.echo(f"No links found for job: {job_id}", err=True)
        raise typer.Exit(code=1)
    source = Path(job.result.links_file_path)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)
        typer.echo(f"Links copied to {output}")
    else:
        typer.echo(source.read_text(encoding="utf-8"))


@app.command("scrape")
def scrape(
    crawl_job_id: str = typer.Argument(..., help="Completed crawl job UUID"),
    embedding_source: str = typer.Option(
        "markdown",
        "--embedding-source",
        help="Embedding input: markdown (page text) or image (screenshot).",
    ),
) -> None:
    """Create a scrape job from a completed crawl."""
    if embedding_source not in {"markdown", "image"}:
        typer.echo("embedding_source must be 'markdown' or 'image'", err=True)
        raise typer.Exit(code=1)
    service = ScrapeService()
    with session_scope() as session:
        job = service.create_scrape_job(
            session,
            crawl_job_id=uuid.UUID(crawl_job_id),
            embedding_source=embedding_source,
        )
        job_id = job.id
    enqueue_scrape(job_id)
    typer.echo(f"Scrape job created: {job_id} (embedding_source={embedding_source})")


if __name__ == "__main__":
    app()
