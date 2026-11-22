import json
import os
from pathlib import Path
from dotenv import load_dotenv


from groq import (
    Groq,
    APIConnectionError,
    APIStatusError,
    RateLimitError
)


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")


GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "llama-3.3-70b-versatile"
)


def generate_response(
    system_prompt: str,
    user_prompt: str
) -> dict:

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    if not system_prompt.strip() or not user_prompt.strip():
        raise ValueError("Prompts cannot be empty.")

    client = Groq(api_key=api_key)

    try:
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
            raise ValueError("Groq returned an empty response.")

        return json.loads(content)

    except (APIConnectionError, RateLimitError, APIStatusError) as error:
        raise RuntimeError(
            f"Groq API request failed: {error}"
        ) from error

    except json.JSONDecodeError as error:
        raise ValueError(
            "Groq returned an invalid JSON response."
        ) from error