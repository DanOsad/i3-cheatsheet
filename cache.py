
#!/usr/bin/env python3

"""Cache management for i3-cheatsheet."""

import hashlib
import json
import os
import tempfile

from pathlib import Path

from parser import I3Parser


CACHE_VERSION = 1
CACHE_DIR = Path.home() / ".cache" / "i3-cheatsheet"

BINDINGS_FILE = CACHE_DIR / "bindings.json"
STATE_FILE = CACHE_DIR / "state.json"

def make_dir(path: Path) -> bool:
    # TODO: implement
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except:
        return False
    return False

def file_metadata(path: Path) -> dict:
    stat = path.stat()

    return {
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65536), b""):
            digest.update(chunk)

    return digest.hexdigest()


def atomic_write(path: Path, content: str):
    """Write a file atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=".tmp-",
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_path, path)

    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


class CacheManager:

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path).expanduser().resolve()

    def load(self) -> dict:
        """Load bindings, rebuilding the cache when necessary."""

        state = load_json(STATE_FILE)
        cached = load_json(BINDINGS_FILE)

        if (
            state
            and cached
            and state.get("version") == CACHE_VERSION
            and cached.get("version") == CACHE_VERSION
            and self._metadata_unchanged(state)
        ):
            return cached

        if (
            state
            and cached
            and state.get("version") == CACHE_VERSION
            and cached.get("version") == CACHE_VERSION
            and self._hashes_unchanged(state)
        ):
            self._update_metadata(state)
            return cached

        return self._rebuild()

    def _metadata_unchanged(self, state: dict) -> bool:
        sources = state.get("sources", {})

        if not sources:
            return False

        for filename, previous in sources.items():
            path = Path(filename)

            try:
                current = file_metadata(path)
            except OSError:
                return False

            if current != previous.get("metadata"):
                return False

        return True

    def _hashes_unchanged(self, state: dict) -> bool:
        sources = state.get("sources", {})

        if not sources:
            return False

        for filename, previous in sources.items():
            path = Path(filename)

            try:
                if file_hash(path) != previous.get("sha256"):
                    return False
            except OSError:
                return False

        return True

    def _update_metadata(self, state: dict):
        for filename, entry in state["sources"].items():
            entry["metadata"] = file_metadata(Path(filename))

        atomic_write(
            STATE_FILE,
            json.dumps(state, indent=2) + "\n",
        )

    def _rebuild(self) -> dict:
        parser = I3Parser()
        bindings = parser.parse(self.config_path)

        sources = {}

        for path in sorted(parser.files):
            sources[str(path)] = {
                "metadata": file_metadata(path),
                "sha256": file_hash(path),
            }

        result = {
            "version": CACHE_VERSION,
            "bindings": bindings,
            "binding_count": len(bindings),
            "files": sorted(sources),
        }

        state = {
            "version": CACHE_VERSION,
            "sources": sources,
        }

        atomic_write(
            BINDINGS_FILE,
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        )

        atomic_write(
            STATE_FILE,
            json.dumps(state, indent=2) + "\n",
        )

        return result

