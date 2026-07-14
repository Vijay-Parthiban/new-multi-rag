from markdownify import markdownify as html_to_markdown


def html_to_markdown_content(html: str, *, title: str | None = None) -> str:
    """Convert HTML to markdown for storage and text embeddings."""
    body = html_to_markdown(html, heading_style="ATX").strip()
    if title:
        return f"# {title}\n\n{body}".strip()
    return body
