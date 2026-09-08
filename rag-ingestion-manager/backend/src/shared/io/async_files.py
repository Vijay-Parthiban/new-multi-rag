import asyncio
from pathlib import Path

import shutil


async def write_bytes(path: Path, data: bytes) -> None:
    await asyncio.to_thread(path.write_bytes, data)


async def read_bytes(path: Path) -> bytes:
    return await asyncio.to_thread(path.read_bytes)


async def unlink(path: Path, missing_ok: bool = False) -> None:
    await asyncio.to_thread(path.unlink, missing_ok=missing_ok)


async def move(src: Path, dest: Path) -> None:
    await asyncio.to_thread(shutil.move, str(src), str(dest))


async def rmtree(path: Path) -> None:
    await asyncio.to_thread(shutil.rmtree, path, True)


async def mkdir(path: Path) -> None:
    await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)


async def path_exists(path: Path) -> bool:
    return await asyncio.to_thread(path.exists)


async def stat_size(path: Path) -> int:
    return (await asyncio.to_thread(path.stat)).st_size


async def append_file(target: Path, source: Path) -> None:
    def _append() -> None:
        with target.open("ab") as out, source.open("rb") as inp:
            shutil.copyfileobj(inp, out)

    await asyncio.to_thread(_append)


async def rename_path(old: Path, new: Path) -> None:
    await asyncio.to_thread(old.rename, new)


async def stitch_files(chunk_paths: list[Path], dest: Path) -> int:
    def _stitch() -> int:
        written = 0
        with dest.open("wb") as out:
            for chunk_path in chunk_paths:
                data = chunk_path.read_bytes()
                out.write(data)
                written += len(data)
        return written

    return await asyncio.to_thread(_stitch)
