from pydantic import BaseModel, Field

from backend.services.context_builder import build_ai_context
from backend.services.llm_service import generate_response


class TailoredParagraph(BaseModel):
    paragraph_id: str
    rewritten_text: str
    matched_requirements: list[str] = Field(default_factory=list)


class RIEngineResponse(BaseModel):
    professional_summary: str | None = None
    tailored_paragraphs: list[TailoredParagraph] = Field(default_factory=list)
    changes_summary: list[str] = Field(default_factory=list)


def run_ri_engine(resume_id: int, job_description: str) -> dict:

    if not isinstance(job_description, str) or not job_description.strip():
        raise ValueError("Job description cannot be empty.")

    ai_context = build_ai_context(
        resume_id,
        job_description
    )

    formatting_lookup = {
        item["id"]: item
        for item in ai_context["resume_formatting"].get("paragraphs", [])
    }

    header_types = {"header", "personal_info"}

    ai_context["resume_paragraphs"] = [
        paragraph
        for paragraph in ai_context["resume_paragraphs"]
        if formatting_lookup.get(
            paragraph["paragraph_id"], {}
        ).get("t") not in header_types
    ]

    available_paragraph_ids = {
        paragraph["paragraph_id"]
        for paragraph in ai_context["resume_paragraphs"]
    }

    system_prompt = """
You are a Resume Intelligence Engine.

Your task is to tailor retrieved resume content to a job description.

STRICT RULES:
1. Use only information present in the supplied resume context.
2. Never invent skills, qualifications, responsibilities, achievements,
   metrics, employers, or experience.
3. Do not change the factual meaning of any resume statement.
4. Improve relevance, clarity, and alignment with the job requirements.
5. Preserve technical terminology and factual details.
6. Every selected paragraph must retain its original paragraph_id.
7. Return ONLY paragraphs that are relevant to the target role.
8. Do not return paragraphs that are irrelevant to the target role.
9. Do not return header or personal contact information.
10. Do not create new resume content unsupported by the source.
11. Return valid JSON matching the requested structure.

The professional summary must also be based exclusively on the
supplied resume content.

A paragraph that you select may be rewritten or retained with improved
wording. The output must contain every paragraph you want included
in the final resume. Any paragraph you do not return will be excluded.
"""

    user_prompt = f"""
Tailor the retrieved resume content to the supplied job description.

RESUME CONTEXT:
{ai_context}

Return JSON with this structure:

{{
    "professional_summary": "Tailored professional summary",
    "tailored_paragraphs": [
        {{
            "paragraph_id": "P10",
            "rewritten_text": "Selected or rewritten paragraph",
            "matched_requirements": ["R001", "R002"]
        }}
    ],
    "changes_summary": [
        "Brief explanation of a change"
    ]
}}

Only use paragraph IDs and requirement IDs supplied in the context.
Return only the paragraphs you want included in the final resume.
"""

    response = generate_response(
        system_prompt=system_prompt,
        user_prompt=user_prompt
    )

    validated_response = RIEngineResponse.model_validate(response)

    returned_ids = [
        paragraph.paragraph_id
        for paragraph in validated_response.tailored_paragraphs
    ]

    if len(returned_ids) != len(set(returned_ids)):
        raise ValueError("RIE returned duplicate paragraph IDs.")

    invalid_ids = set(returned_ids) - available_paragraph_ids

    if invalid_ids:
        raise ValueError(
            f"RIE returned unknown paragraph IDs: {sorted(invalid_ids)}"
        )

    return validated_response.model_dump()