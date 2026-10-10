"""Anthropic Claude provider (KRONOS_LLM_PROVIDER=anthropic).

Optional: the `anthropic` package is imported only when no client is injected, so the mock path,
tests and CI never need it. Output is constrained with structured outputs
(`output_config.format` = a JSON schema generated from the pydantic models at call time), and
AgentService still validates the reply and the engine still decides whether it applies.
"""

import copy
import json
import os
import typing
from typing import Any

from pydantic import TypeAdapter

from kronos_agents.prompts import system_prompt, user_message
from kronos_agents.provider import AgentService, ProviderError

# Haiku: each decision is one choice from a short menu, so the fast, low-cost model fits.
# Set KRONOS_LLM_MODEL (e.g. claude-sonnet-5-5) for richer reasoning.
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_TIMEOUT = 20.0
# Models that accept server-side refusal fallbacks (`fallbacks: "default"`).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_TASK_METHODS = {"decision": "decide", "ask": "ask", "intervention": "parse"}
# JSON-schema keywords structured outputs do not support; folded into the description instead
# and still enforced by pydantic when AgentService validates the reply.
_UNSUPPORTED = (
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
)
_WRAPPER = "result"
# Structured outputs compile the schema into a grammar with a size limit: a union of more
# than about 8 action types is rejected ("compiled grammar is too large"). Larger menus send
# the schema as text in the prompt instead; AgentService still validates every reply.
GRAMMAR_LIMIT = 8


def result_type(task: str) -> Any:
    """The model AgentService validates this task against, read from its return annotation so
    the schema follows models.py (e.g. a widened intervention union) without edits here."""
    method = getattr(AgentService, _TASK_METHODS[task])
    return typing.get_type_hints(method, include_extras=True)["return"]


def _strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_strict(item) for item in node]
    if not isinstance(node, dict):
        return node
    node = dict(node)
    node.pop("discriminator", None)
    node.pop("default", None)
    notes = {key: node.pop(key) for key in _UNSUPPORTED if key in node}
    if "oneOf" in node:
        node["anyOf"] = node.pop("oneOf")
    if "const" in node:
        node["enum"] = [node.pop("const")]
    if notes:
        hint = ", ".join(f"{key}: {value}" for key, value in notes.items())
        node["description"] = f"{node.get('description', '')} ({hint})".strip()
    result = {key: _strict(value) for key, value in node.items()}
    if result.get("type") == "object":
        result.setdefault("properties", {})
        result["additionalProperties"] = False
    return result


def _require_fields(definition: dict, fields: tuple[str, ...]) -> None:
    """Fields with pydantic defaults (`type`, `rationale`) that the model must still send."""
    props = definition.get("properties", {})
    if "rationale" in fields and "rationale" in props:
        props["rationale"] = {
            "type": "string",
            "description": "One first-person sentence explaining the choice (max 300 chars).",
        }
    required = definition.setdefault("required", [])
    required.extend(f for f in fields if f in props and f not in required)


def output_schema(task: str, observation: dict) -> tuple[dict, bool]:
    """Structured-output schema for a task, and whether the reply is wrapped in `result`.
    Decisions are narrowed to the observation's `available_actions` and must give a rationale;
    every variant of a tagged union must state its `type`."""
    schema = TypeAdapter(result_type(task)).json_schema()
    mapping = schema.get("discriminator", {}).get("mapping", {})
    if task == "decision":
        allowed = observation.get("available_actions") or list(mapping)
        refs = [mapping[name] for name in allowed if name in mapping]
        if not refs:
            raise ProviderError("No available action is part of the AgentAction schema")
        schema = {"$defs": schema["$defs"], "anyOf": [{"$ref": ref} for ref in refs]}
        for ref in set(mapping.values()) - set(refs):
            schema["$defs"].pop(ref.rsplit("/", 1)[-1], None)
        mapping = {name: mapping[name] for name in allowed if name in mapping}
    fields = ("type", "rationale") if task == "decision" else ("type",)
    for ref in mapping.values():
        _require_fields(schema["$defs"][ref.rsplit("/", 1)[-1]], fields)
    schema = _strict(copy.deepcopy(schema))
    if schema.get("type") == "object":
        return schema, False
    # The root of a structured output must be an object: wrap unions, unwrap the reply.
    defs = schema.pop("$defs", None)
    wrapped = {
        "type": "object",
        "properties": {_WRAPPER: schema},
        "required": [_WRAPPER],
        "additionalProperties": False,
    }
    if defs:
        wrapped["$defs"] = defs
    return wrapped, True


def _api_detail(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return message[:200] if isinstance(message, str) else ""


def _error_message(exc: Exception) -> str:
    """Map SDK failures to short messages. Never includes request headers or the API key."""
    try:
        import anthropic
    except ImportError:  # injected fake clients raise their own errors
        anthropic = None
    if isinstance(exc, TimeoutError):
        return "Claude request timed out"
    if anthropic is not None:
        if isinstance(exc, anthropic.APITimeoutError):
            return "Claude request timed out"
        if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
            return "Claude rejected the API key (check ANTHROPIC_API_KEY)"
        if isinstance(exc, anthropic.RateLimitError):
            return "Claude rate limit reached"
        if isinstance(exc, anthropic.BadRequestError):
            # The API's own explanation (e.g. "credit balance is too low") never holds the key.
            detail = _api_detail(exc)
            return "Claude rejected the request" + (f": {detail}" if detail else " (bad request)")
        if isinstance(exc, anthropic.APIStatusError):
            return f"Claude API error (HTTP {exc.status_code})"
        if isinstance(exc, anthropic.APIConnectionError):
            return "Could not reach the Claude API"
    return f"Claude call failed ({type(exc).__name__})"


class AnthropicProvider:
    """LLMProvider backed by the Anthropic Messages API. Inject `client` in tests."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        client: Any = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_tokens: int = 4096,
        effort: str = "low",
    ):
        self.model, self.max_tokens, self.effort = model, max_tokens, effort
        if client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise ProviderError(
                    "KRONOS_LLM_PROVIDER=anthropic needs the SDK: uv sync --extra anthropic"
                ) from exc
            key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise ProviderError("KRONOS_LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
            # AgentService owns retries; the SDK retries once more on transient HTTP errors.
            client = anthropic.AsyncAnthropic(api_key=key, timeout=timeout, max_retries=1)
        self.client = client

    def request(self, task: str, observation: dict) -> tuple[dict, bool]:
        """Keyword arguments for `client.beta.messages.create` (pure; inspected by tests) and
        whether the structured reply is wrapped."""
        schema, wrapped = output_schema(task, observation)
        message = user_message(task, observation)
        constrained = not (
            task == "decision" and len(observation.get("available_actions") or []) > GRAMMAR_LIMIT
        )
        if not constrained:
            # Too many choices for a grammar: describe the shapes and ask for bare JSON.
            shapes = json.dumps(
                schema["properties"][_WRAPPER] | {"$defs": schema.get("$defs", {})},
                separators=(",", ":"),
            )
            message = (
                f"Reply with one JSON object matching this schema (no prose, no code fence):\n"
                f"{shapes}\n\n{message}"
            )
            wrapped = False
        output_config: dict[str, Any] = {"effort": self.effort}
        if constrained:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # Static rules + few-shot examples first, cached; the observation varies.
            "system": [
                {
                    "type": "text",
                    "text": system_prompt(task),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": message}],
            "output_config": output_config,
        }
        if self.model in _FALLBACK_MODELS:
            kwargs["betas"] = [_FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs, wrapped

    async def complete(self, task: str, observation: dict) -> str:
        if task not in _TASK_METHODS:
            raise ProviderError(f"Unknown provider task {task!r}")
        kwargs, wrapped = self.request(task, observation)
        try:
            response = await self.client.beta.messages.create(**kwargs)
        except ProviderError:
            raise
        except Exception as exc:  # SDK/network failures become ProviderError (no retry storm)
            raise ProviderError(_error_message(exc)) from exc
        return self._extract(response, wrapped)

    @staticmethod
    def _extract(response: Any, wrapped: bool) -> str:
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            raise ProviderError("Claude declined this request")
        if stop == "max_tokens":
            raise ProviderError("Claude ran out of output tokens before finishing")
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        if not text.strip():
            raise ProviderError("Claude returned no structured output")
        if not wrapped:
            # Unconstrained replies may wrap the object in prose or a code fence.
            start, end = text.find("{"), text.rfind("}")
            text = text[start : end + 1] if 0 <= start < end else text
            try:
                data = json.loads(text)
            except ValueError:
                return text  # AgentService reports the invalid JSON
            if isinstance(data, dict) and set(data) == {_WRAPPER}:
                data = data[_WRAPPER]  # some replies copy the structured-output wrapper
            return json.dumps(data)
        try:
            return json.dumps(json.loads(text)[_WRAPPER])
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("Claude returned malformed structured output") from exc
