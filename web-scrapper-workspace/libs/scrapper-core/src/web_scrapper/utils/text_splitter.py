import re

def chunk_markdown(text: str, chunk_size: int = 1000, chunk_overlap: int = 100) -> list[str]:
    """
    A native Markdown chunking strategy that splits text cleanly by headers 
    and paragraphs without mid-sentence fracturing.
    """
    if not text or not text.strip():
        return []

    # Split by major markdown headers or double newlines (paragraphs)
    tokens = re.split(r'(^#+\s+.*$|\n{2,})', text, flags=re.MULTILINE)
    
    chunks = []
    current_chunk = []
    current_length = 0

    for token in tokens:
        token_strip = token.strip()
        if not token_strip:
            continue
        
        token_len = len(token_strip)
        
        # If a single piece is larger than chunk_size, hard-slice it cleanly by words
        if token_len > chunk_size:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_length = 0
            
            # Sub-slice long block by spaces
            words = token_strip.split(" ")
            sub_chunk = []
            sub_len = 0
            for word in words:
                if sub_len + len(word) > chunk_size:
                    chunks.append(" ".join(sub_chunk))
                    sub_chunk = [word]
                    sub_len = len(word)
                else:
                    sub_chunk.append(word)
                    sub_len += len(word) + 1
            if sub_chunk:
                current_chunk = sub_chunk
                current_length = sub_len
            continue

        # If adding this token exceeds chunk size, lock the current chunk
        if current_length + token_len > chunk_size:
            chunks.append(" ".join(current_chunk))
            
            # Handle overlap: retain last few items if length permits
            overlap_text = []
            overlap_len = 0
            for t in reversed(current_chunk):
                if overlap_len + len(t) < chunk_overlap:
                    overlap_text.insert(0, t)
                    overlap_len += len(t) + 1
                else:
                    break
            
            current_chunk = overlap_text + [token_strip]
            current_length = overlap_len + token_len + 1
        else:
            current_chunk.append(token_strip)
            current_length += token_len + 1

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return [c for c in chunks if c.strip()]