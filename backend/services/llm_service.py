import json
import os
import logging
from pathlib import Path

from dotenv import load_dotenv
from groq import (
    Groq,
    AuthenticationError,
    APIConnectionError,
    APIStatusError,
    RateLimitError
)


logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_DIR / ".env"

load_dotenv(ENV_PATH)

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "llama-3.3-70b-versatile"
)


def generate_response(
    system_prompt: str,
    user_prompt: str
) -> dict:

    api_key = os.getenv("GROQ_API_KEY", "").strip()

    if not api_key:
        logger.error("GROQ_API_KEY is missing.")
        raise RuntimeError("GROQ_API_KEY is not configured.")

    if not system_prompt.strip() or not user_prompt.strip():
        logger.error("Empty system or user prompt received.")
        raise ValueError("Prompts cannot be empty.")

    logger.info("Initializing Groq client.")
    logger.info("Using Groq model: %s", GROQ_MODEL)
    logger.info("Environment file: %s", ENV_PATH)
    logger.info("API key configured: True")

    try:
        client = Groq(api_key=api_key)

        logger.info("Sending request to Groq.")

        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            temperature=0.2,
            max_tokens=4096,
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content

        if not content:
            logger.error("Groq returned an empty response.")
            raise ValueError("Groq returned an empty response.")

        result = json.loads(content)

        logger.info("Groq request completed successfully.")

        return result

    except AuthenticationError as error:
        logger.error(
            "Groq authentication failed. HTTP status: %s",
            error.status_code
        )
        raise RuntimeError(
            "Groq rejected the API key. Check GROQ_API_KEY."
        ) from error

    except RateLimitError as error:
        logger.error(
            "Groq rate limit exceeded. HTTP status: %s",
            error.status_code
        )
        raise RuntimeError(
            "Groq rate limit exceeded."
        ) from error

    except APIConnectionError:
        logger.exception("Could not connect to Groq API.")
        raise RuntimeError(
            "Could not connect to Groq API."
        )

    except APIStatusError as error:
        logger.error(
            "Groq API returned HTTP %s: %s",
            error.status_code,
            error.message
        )
        raise RuntimeError(
            f"Groq API request failed: HTTP {error.status_code}"
        ) from error

    except json.JSONDecodeError as error:
        logger.exception("Groq returned invalid JSON.")
        raise ValueError(
            "Groq returned an invalid JSON response."
        ) from error