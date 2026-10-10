"""Check that the Anthropic key in .env (or the environment) works, without printing it.

    uv run python scripts/check_anthropic_key.py          # free: lists models
    uv run python scripts/check_anthropic_key.py --call   # also one tiny paid call

Needs `uv sync --extra anthropic`.
"""

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source in ["backend/api/src", "backend/modules/agents/src", "backend/modules/simulation/src"]:
    sys.path.insert(0, str(ROOT / source))

from kronos.config import Settings  # noqa: E402


def describe(key: str) -> str:
    """Prefix and length only; the key itself is never shown."""
    prefix = key.split("-", 3)[:3]
    return f"{'-'.join(prefix)}-… ({len(key)} characters)"


async def main(call: bool) -> int:
    settings = Settings()
    secret = settings.anthropic_api_key
    if secret is None or not secret.get_secret_value().strip():
        print("✗ No ANTHROPIC_API_KEY found.")
        print("  Put `ANTHROPIC_API_KEY=...` in .env (no leading #) and save the file.")
        return 1
    key = secret.get_secret_value().strip()
    print(f"• Key found: {describe(key)}")
    print(f"• KRONOS_LLM_PROVIDER={settings.llm_provider}")

    try:
        from anthropic import AsyncAnthropic, AuthenticationError, PermissionDeniedError
    except ImportError:
        print("✗ The anthropic package is missing. Run: uv sync --extra anthropic")
        return 1

    client = AsyncAnthropic(api_key=key)
    try:
        models = await client.models.list(limit=20)
        ids = [m.id for m in models.data]
        print(f"✓ Key accepted. {len(ids)} models available, e.g. {', '.join(ids[:4])}")
    except (AuthenticationError, PermissionDeniedError) as exc:
        print(f"✗ Key rejected ({exc.status_code}): {exc.message}")
        print("  Create an API key at console.anthropic.com → API Keys.")
        return 1
    except Exception as exc:
        print(f"✗ Could not reach the API: {type(exc).__name__}: {exc}")
        return 1

    if call:
        from kronos_agents.anthropic_provider import DEFAULT_MODEL

        model = DEFAULT_MODEL if settings.llm_model == "deterministic-v1" else settings.llm_model
        try:
            reply = await client.messages.create(
                model=model,
                max_tokens=20,
                messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            )
            text = "".join(b.text for b in reply.content if b.type == "text").strip()
            print(f"✓ {model} replied: {text!r} ({reply.usage.output_tokens} tokens)")
        except Exception as exc:
            message = getattr(exc, "message", str(exc))
            print(f"✗ Call to {model} failed: {message}")
            if "credit balance" in message:
                print("  The key works, but the account has no credits:")
                print("  console.anthropic.com → Plans & Billing.")
            return 1

    if settings.llm_provider != "anthropic":
        print("→ To use Claude in the village, set KRONOS_LLM_PROVIDER=anthropic in .env,")
        print("  remove KRONOS_LLM_MODEL=deterministic-v1, and restart `make backend`.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--call", action="store_true", help="also make one tiny paid call")
    sys.exit(asyncio.run(main(parser.parse_args().call)))
