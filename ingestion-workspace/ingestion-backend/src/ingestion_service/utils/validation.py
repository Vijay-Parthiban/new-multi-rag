import re

COLLECTION_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,127}$")


def validate_qdrant_collection(name: str) -> str:
    cleaned = name.strip()
    if not COLLECTION_PATTERN.match(cleaned):
        raise ValueError(
            "Collection name must be 3–128 chars, start with alphanumeric, "
            "and contain only letters, numbers, hyphens, underscores."
        )
    return cleaned


def validate_description(description: str) -> str:
    cleaned = description.strip()
    if len(cleaned) < 8:
        raise ValueError("Pipeline description must be at least 8 characters.")
    if len(cleaned) > 512:
        raise ValueError("Pipeline description must be at most 512 characters.")
    return cleaned
