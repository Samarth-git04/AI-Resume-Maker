import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from cerebras.cloud.sdk import (
    Cerebras,
    APIConnectionError,
    APIStatusError,
    RateLimitError,
)

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

API_KEY = os.getenv("CEREBRAS_API_KEY")
MODEL = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b")

client = Cerebras(api_key=API_KEY) if API_KEY else None


def generate_response(system_prompt: str, user_prompt: str) -> dict:
    if (
        not isinstance(system_prompt, str)
        or not system_prompt.strip()
        or not isinstance(user_prompt, str)
        or not user_prompt.strip()
    ):
        raise ValueError("System prompt and user prompt cannot be empty.")

    if client is None:
        raise RuntimeError("CEREBRAS_API_KEY is missing from backend/.env")

    started = time.perf_counter()
    logger.info(
        "Cerebras request started. model=%s system_chars=%d user_chars=%d",
        MODEL,
        len(system_prompt),
        len(user_prompt),
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_completion_tokens=8192,
            response_format={"type": "json_object"},
        )

        choice = response.choices[0]
        content = choice.message.content

        # Never log the full model message: it may contain personal resume data
        # or hidden reasoning. Log only safe operational metadata.
        logger.info("Cerebras finish reason: %s", choice.finish_reason)

        if not content or not content.strip():
            raise ValueError("Cerebras returned an empty response.")

        try:
            result = json.loads(content)
        except json.JSONDecodeError as error:
            logger.exception("Cerebras returned invalid JSON.")
            raise ValueError(f"Cerebras returned invalid JSON: {error}") from error

        if not isinstance(result, dict):
            raise ValueError("Cerebras response must be a JSON object.")

        usage = response.usage
        logger.info(
            "Cerebras request completed. model=%s duration=%.2fs "
            "prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            MODEL,
            time.perf_counter() - started,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
            getattr(usage, "total_tokens", None),
        )
        return result

    except RateLimitError as error:
        logger.exception("Cerebras rate limit exceeded.")
        raise RuntimeError(f"Cerebras rate limit exceeded: {error}") from error
    except APIConnectionError as error:
        logger.exception("Cerebras API connection failed.")
        raise RuntimeError(f"Could not connect to Cerebras API: {error}") from error
    except APIStatusError as error:
        logger.exception("Cerebras API returned status code %s.", error.status_code)
        raise RuntimeError(
            f"Cerebras API error ({error.status_code}): {error}"
        ) from error
    except (ValueError, RuntimeError):
        raise
    except Exception:
        logger.exception("Unexpected error during Cerebras request.")
        raise
