import json
from pathlib import Path

from src.ingestion_service.core.page_yielder import iter_file_pages


def test_iter_plain_text_file(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello ingestion", encoding="utf-8")

    pages = list(iter_file_pages(file_path, "text/plain", "notes.txt"))

    assert len(pages) == 1
    assert pages[0].page_index == 0
    assert pages[0].text == "hello ingestion"


def test_iter_json_file(tmp_path: Path) -> None:
    file_path = tmp_path / "data.json"
    file_path.write_text(json.dumps([{"id": 1}, {"id": 2}]), encoding="utf-8")

    pages = list(iter_file_pages(file_path, "application/json", "data.json"))

    assert len(pages) == 2
    assert '"id": 1' in pages[0].text
    assert '"id": 2' in pages[1].text


def test_iter_csv_file(tmp_path: Path) -> None:
    file_path = tmp_path / "rows.csv"
    file_path.write_text("name,role\nAlex,Engineer\n", encoding="utf-8")

    pages = list(iter_file_pages(file_path, "text/csv", "rows.csv"))

    assert len(pages) == 1
    assert "Alex, Engineer" in pages[0].text
