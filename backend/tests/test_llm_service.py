import pytest
from unittest.mock import patch, MagicMock

from backend.services.llm_service import generate_response


SYSTEM_PROMPT = "You are a resume assistant."
USER_PROMPT = "Analyze this resume."


@patch("backend.services.llm_service.Groq")
def test_successful_response(mock_groq):

    mock_client = MagicMock()
    mock_groq.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices[0].message.content = (
        '{"status": "success", "score": 85}'
    )

    mock_client.chat.completions.create.return_value = mock_response

    with patch.dict("os.environ", {"GROQ_API_KEY": "test_key"}):

        result = generate_response(
            SYSTEM_PROMPT,
            USER_PROMPT
        )

    assert result == {
        "status": "success",
        "score": 85
    }

    mock_client.chat.completions.create.assert_called_once()


@patch("backend.services.llm_service.Groq")
def test_invalid_json_response(mock_groq):

    mock_client = MagicMock()
    mock_groq.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Invalid JSON"

    mock_client.chat.completions.create.return_value = mock_response

    with patch.dict("os.environ", {"GROQ_API_KEY": "test_key"}):

        with pytest.raises(ValueError, match="invalid JSON"):
            generate_response(
                SYSTEM_PROMPT,
                USER_PROMPT
            )


def test_missing_api_key():

    with patch.dict("os.environ", {}, clear=True):

        with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
            generate_response(
                SYSTEM_PROMPT,
                USER_PROMPT
            )


def test_empty_system_prompt():

    with pytest.raises(ValueError, match="Prompts cannot be empty"):
        generate_response(
            "",
            USER_PROMPT
        )


def test_empty_user_prompt():

    with pytest.raises(ValueError, match="Prompts cannot be empty"):
        generate_response(
            SYSTEM_PROMPT,
            ""
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])