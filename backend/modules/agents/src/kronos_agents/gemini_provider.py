"""Google Gemini provider (KRONOS_LLM_PROVIDER=gemini).

Optional: the `google-genai` package is imported only when no client is injected, so the mock
path, tests and CI never need it. Replies use JSON mode constrained by the same schema the
Claude provider builds (`output_schema`); the player's toolkit is sent as native function
declarations. AgentService still validates every reply and the engine still decides.
"""

import json
import os
from typing import Any

from kronos_agents.anthropic_provider import _WRAPPER, GRAMMAR_LIMIT, output_schema
from kronos_agents.prompts import system_prompt, user_message
from kronos_agents.provider import ProviderError
from kronos_agents.tools import tool_definitions

# Cost split: villager decisions are most of the volume (up to 24 a day) and are one choice
# from a short menu, so they use Flash-Lite, the cheapest tier. Player-facing calls (god-mode
# queries and Ask) are rare and read directly, so they use Flash for better judgment.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
PLAYER_MODEL = "gemini-3.5-flash"
DEFAULT_TIMEOUT = 20.0
_TASKS = {"decision", "ask", "intervention"}


def _error_message(exc: Exception) -> str:
    """Map SDK failures to short messages. Never includes request headers or the API key."""
    if isinstance(exc, TimeoutError):
        return "Gemini request timed out"
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        if code in (401, 403):
            return "Gemini rejected the API key (check GEMINI_API_KEY)"
        if code == 429:
            return "Gemini rate limit or quota reached"
        detail = getattr(exc, "message", None)
        detail = detail[:200] if isinstance(detail, str) else ""
        return f"Gemini API error (HTTP {code})" + (f": {detail}" if detail else "")
    name = type(exc).__name__
    if "Timeout" in name:
        return "Gemini request timed out"
    if "Connect" in name:
        return "Could not reach the Gemini API"
    return f"Gemini call failed ({name})"


def _parts(response: Any) -> list[Any]:
    candidates = getattr(response, "candidates", None) or []
    content = getattr(candidates[0], "content", None) if candidates else None
    return list(getattr(content, "parts", None) or [])


def _finish(response: Any) -> str:
    candidates = getattr(response, "candidates", None) or []
    reason = getattr(candidates[0], "finish_reason", None) if candidates else None
    return str(getattr(reason, "name", reason) or "")


class GeminiProvider:
    """LLMProvider backed by the Gemini API (google-genai). Inject `client` in tests."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        player_model: str = PLAYER_MODEL,
        client: Any = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_tokens: int = 4096,
    ):
        self.model, self.player_model, self.max_tokens = model, player_model, max_tokens
        if client is None:
            try:
                from google import genai
            except ImportError as exc:
                raise ProviderError(
                    "KRONOS_LLM_PROVIDER=gemini needs the SDK: uv sync --extra gemini"
                ) from exc
            key = api_key or os.environ.get("GEMINI_API_KEY")
            if not key:
                raise ProviderError("KRONOS_LLM_PROVIDER=gemini needs GEMINI_API_KEY")
            client = genai.Client(api_key=key, http_options={"timeout": int(timeout * 1000)})
        self.client = client

    @staticmethod
    def _thinking(model: str) -> dict:
        # One choice from a menu needs little thought; keep latency and cost low.
        if model.startswith("gemini-2"):
            return {"thinking_budget": 0} if "flash" in model else {}
        return {"thinking_level": "low"}

    def request(self, task: str, observation: dict) -> tuple[dict, bool]:
        """Keyword arguments for `client.aio.models.generate_content` (pure; inspected by tests)
        and whether the reply is wrapped in `result`."""
        schema, wrapped = output_schema(task, observation)
        message = user_message(task, observation)
        model = self.player_model if task == "ask" else self.model
        config: dict[str, Any] = {
            "system_instruction": system_prompt(task),
            "max_output_tokens": self.max_tokens,
            "response_mime_type": "application/json",
            "thinking_config": self._thinking(model),
        }
        if task == "decision" and len(observation.get("available_actions") or []) > GRAMMAR_LIMIT:
            # A long menu: describe the shapes in the prompt and ask for bare JSON.
            shapes = json.dumps(
                schema["properties"][_WRAPPER] | {"$defs": schema.get("$defs", {})},
                separators=(",", ":"),
            )
            message = f"Reply with one JSON object matching this schema:\n{shapes}\n\n{message}"
            wrapped = False
        else:
            config["response_json_schema"] = schema
        return {"model": model, "contents": message, "config": config}, wrapped

    def tool_request(self, query: str, context: dict) -> dict:
        """Keyword arguments for a player query with native function calling (pure; for tests)."""
        declarations = [
            {
                "name": tool["name"],
                "description": tool["description"],
                "parameters_json_schema": tool["input_schema"],
            }
            for tool in tool_definitions()
        ]
        return {
            "model": self.player_model,
            "contents": user_message("user_query", {"query": query, "context": context}),
            "config": {
                "system_instruction": system_prompt("user_query"),
                "max_output_tokens": 1024,
                "tools": [{"function_declarations": declarations}],
                "automatic_function_calling": {"disable": True},
                "thinking_config": self._thinking(self.player_model),
            },
        }

    async def _generate(self, kwargs: dict) -> Any:
        try:
            return await self.client.aio.models.generate_content(**kwargs)
        except ProviderError:
            raise
        except Exception as exc:  # SDK/network failures become ProviderError
            raise ProviderError(_error_message(exc)) from exc

    async def choose_tool(self, query: str, context: dict) -> tuple[str | None, dict, str]:
        """(tool name, arguments, text): the function Gemini called, or None and its reply."""
        response = await self._generate(self.tool_request(query, context))
        parts = _parts(response)
        text = " ".join(
            p.text.strip()
            for p in parts
            if getattr(p, "text", None) and not getattr(p, "thought", False) and p.text.strip()
        )
        for part in parts:
            call = getattr(part, "function_call", None)
            if call is not None and getattr(call, "name", None):
                return call.name, dict(call.args or {}), text
        if not text:
            if _finish(response) in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
                raise ProviderError("Gemini declined this request")
            raise ProviderError("Gemini returned neither a tool call nor a reply")
        return None, {}, text

    async def complete(self, task: str, observation: dict) -> str:
        if task not in _TASKS:
            raise ProviderError(f"Unknown provider task {task!r}")
        kwargs, wrapped = self.request(task, observation)
        response = await self._generate(kwargs)
        finish = _finish(response)
        if finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST"):
            raise ProviderError("Gemini declined this request")
        if finish == "MAX_TOKENS":
            raise ProviderError("Gemini ran out of output tokens before finishing")
        text = "".join(
            p.text for p in _parts(response) if getattr(p, "text", None) and not p.thought
        )
        if not text.strip():
            raise ProviderError("Gemini returned no output")
        start, end = text.find("{"), text.rfind("}")
        text = text[start : end + 1] if 0 <= start < end else text
        try:
            data = json.loads(text)
        except ValueError:
            return text  # AgentService reports the invalid JSON
        if isinstance(data, dict) and set(data) == {_WRAPPER}:
            data = data[_WRAPPER]
        elif wrapped and isinstance(data, dict) and _WRAPPER in data:
            data = data[_WRAPPER]
        return json.dumps(data)
