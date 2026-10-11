"""Provider wrappers: a response cache for cheap, offline replays and a local debug log.

Both wrap any `LLMProvider` and keep its `source`, so proposals stay tagged honestly.
"""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from kronos_agents.provider import LLMProvider, ProviderError


def _without_branch(value):
    """Drop branch IDs so a replay on a fork of the same history reuses the same answers."""
    if isinstance(value, dict):
        return {k: _without_branch(v) for k, v in value.items() if k != "branch_id"}
    if isinstance(value, list):
        return [_without_branch(v) for v in value]
    return value


def cache_key(task: str, observation: dict, tag: str = "") -> str:
    """Stable key for one call: the task, what the citizen saw, and the provider tag
    (model + prompt version). The observation already pins the world state and citizen."""
    body = json.dumps(
        {"task": task, "tag": tag, "observation": _without_branch(observation)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()


class CachingProvider:
    """Serves a stored reply when the same call was answered before; otherwise asks the
    wrapped provider and stores replies that parse as JSON.

    `replay_only=True` never calls the wrapped provider: a miss raises ProviderError, so
    the fallback decides instead. Use it for demo runs and replays that must cost nothing.
    """

    def __init__(
        self, inner: LLMProvider, directory: str | Path, *, tag: str = "", replay_only=False
    ):
        self.inner, self.directory, self.tag = inner, Path(directory), tag
        self.replay_only = replay_only
        self.hits = self.misses = 0

    @property
    def source(self):
        return getattr(self.inner, "source", "llm")

    def __getattr__(self, name: str):
        """Pass through what this wrapper doesn't handle, such as `choose_tool`
        (native tool use for player queries; not cached: each query is new)."""
        return getattr(self.inner, name)

    def path(self, task: str, observation: dict) -> Path:
        key = cache_key(task, observation, self.tag)
        return self.directory / task / key[:2] / f"{key}.json"

    async def complete(self, task: str, observation: dict) -> str:
        path = self.path(task, observation)
        if path.exists():
            self.hits += 1
            return path.read_text()
        self.misses += 1
        if self.replay_only:
            raise ProviderError("No cached response for this call (replay-only cache)")
        raw = await self.inner.complete(task, observation)
        try:
            json.loads(raw)
        except ValueError:
            return raw  # Never cache output that cannot be a valid reply.
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically so a crash or a concurrent reader never sees half a file.
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as tmp:
            tmp.write(raw)
        os.replace(tmp.name, path)
        return raw


class LoggingProvider:
    """Appends each call (task, observation, seconds, reply or error) to a local JSONL file
    for debugging. Holds no credentials: providers keep keys in their own clients."""

    def __init__(self, inner: LLMProvider, path: str | Path):
        self.inner, self.path = inner, Path(path)

    @property
    def source(self):
        return getattr(self.inner, "source", "llm")

    def __getattr__(self, name: str):
        """Pass through what this wrapper doesn't handle, such as `choose_tool`
        (native tool use for player queries; not cached: each query is new)."""
        return getattr(self.inner, name)

    async def complete(self, task: str, observation: dict) -> str:
        started = time.perf_counter()
        record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "task": task}
        try:
            raw = await self.inner.complete(task, observation)
            record["reply"] = raw
            return raw
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            record["seconds"] = round(time.perf_counter() - started, 3)
            record["observation"] = observation
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as log:
                log.write(json.dumps(record, sort_keys=True) + "\n")
