from pydantic import BaseModel, Field

from backend.services.context_builder import build_ai_context
from backend.services.llm_service import generate_response

from sqlalchemy.orm import Session

import logging

logger = logging.getLogger(__name__)

from typing import Literal
class ParagraphDecision(BaseModel):
    source_paragraph_ids: list[str]
    action: Literal["keep", "rewrite", "remove", "consolidate"]
    section_name: str | None = None
    rewritten_text: str | None = None
    matched_requirements: list[str] = Field(default_factory=list)

class RIEngineResponse(BaseModel):
    professional_summary: str | None = None
    paragraph_decisions: list[ParagraphDecision] = Field(default_factory=list)
    changes_summary: list[str] = Field(default_factory=list)


def run_ri_engine(
    db: Session,
    resume_id: int,
    job_description: str
) -> dict:

    if not isinstance(job_description, str) or not job_description.strip():
        raise ValueError("Job description cannot be empty.")

    ai_context = build_ai_context(
        db,
        resume_id,
        job_description
    )
    logger.info(
        "AI context received. Resume paragraphs=%s, requirements=%s",
        len(ai_context["resume_paragraphs"]),
        len(ai_context["job_requirements"])
    )

    formatting_lookup = {
        item["id"]: item
        for item in ai_context["resume_formatting"].get("paragraphs", [])
    }

    header_types = {"header", "personal_info"}

    header_ids = {
        item["id"]
        for item in ai_context["resume_formatting"].get("paragraphs", [])[:3]
    }

    logger.info(
        "Paragraph classification: %s",
        [
            (
                p["paragraph_id"],
                formatting_lookup.get(p["paragraph_id"], {}).get("t")
            )
            for p in ai_context["resume_paragraphs"]
        ]
    )

    ai_context["resume_paragraphs"] = [
        paragraph
        for paragraph in ai_context["resume_paragraphs"]
        if (
            paragraph["paragraph_id"] not in header_ids
            and formatting_lookup.get(
                paragraph["paragraph_id"], {}
            ).get("t") not in header_types
        )
    ]

    available_paragraph_ids = {
        paragraph["paragraph_id"]
        for paragraph in ai_context["resume_paragraphs"]
    }

    ai_context["resume_formatting"]["paragraphs"] = [
        item
        for item in ai_context["resume_formatting"].get("paragraphs", [])
        if item["id"] in available_paragraph_ids
    ]

    logger.info(
        "Paragraphs remaining after header filtering: %s",
        len(ai_context["resume_paragraphs"])
    )

    logger.info(
        "Available paragraph IDs: %s",
        [p["paragraph_id"] for p in ai_context["resume_paragraphs"]]
    )

    system_prompt = """
You are an intelligent Resume Intelligence Engine.
Your task is to tailor a candidate's resume to a target job description.
EDITORIAL RESPONSIBILITIES:
You have editorial freedom to decide which content should remain in the
final resume.
For every relevant source paragraph, choose one action:
1. keep:
   Retain the original paragraph without changing its wording.
2. rewrite:
   Improve the paragraph's clarity, relevance, structure, and impact
   while preserving its factual meaning.
3. remove:
   Exclude content that is irrelevant, redundant, generic, or adds
   insufficient value to the target role.
4. consolidate:
   Combine two or more related paragraphs into one stronger paragraph.
   Preserve all relevant factual information and reference every
   source paragraph used.
PROFESSIONAL SUMMARY:
- Generate a concise, tailored professional summary.
- Use only facts supported by the supplied resume.
- Do not repeat achievements or responsibilities unnecessarily.
- Do not simply reproduce the original profile paragraph.

SECTION ORGANIZATION:

- Assign each retained paragraph to its appropriate original resume section.
- Preserve the original section names wherever possible.
- Do not place achievements under professional experience or vice versa.
- Do not create sections unsupported by the original resume.

FACTUAL INTEGRITY:
- Never invent skills, qualifications, responsibilities, achievements,
  employers, dates, metrics, or experience.
- Never change numerical values or factual claims.
- Never invent technologies or tools.
- Preserve the meaning of the original content.
- Do not exaggerate the candidate's experience.

OUTPUT RULES:
- Every source paragraph must appear in exactly one decision.
- Use all original paragraph IDs supplied in the context.
- A consolidated decision must reference at least two source paragraphs.
- A removed paragraph must have null section_name and rewritten_text.
- A kept paragraph must have null rewritten_text.
- A rewritten or consolidated paragraph must have non-empty rewritten_text.
- Return valid JSON matching the requested structure.
- Return no additional text.
- MAKE SURE THE OUTPUT IS NO LONGER THAN 2 PAGES AND YOU ONLY SELECT 3 KEY PROJECTS
"""

    user_prompt = f"""
Tailor the resume to the supplied job description.
RESUME CONTEXT:
{ai_context}
For every source paragraph, return exactly one editorial decision.
Use this JSON structure:
{{
    "professional_summary": "Tailored professional summary",
    "paragraph_decisions": [
        {{
            "source_paragraph_ids": ["P7"],
            "action": "rewrite",
            "section_name": "Key Achievements",
            "rewritten_text": "Improved paragraph text",
            "matched_requirements": ["R001", "R002"]
        }},
        {{
            "source_paragraph_ids": ["P8"],
            "action": "keep",
            "section_name": "Key Achievements",
            "rewritten_text": null,
            "matched_requirements": ["R003"]
        }},
        {{
            "source_paragraph_ids": ["P9"],
            "action": "remove",
            "section_name": null,
            "rewritten_text": null,
            "matched_requirements": []
        }},
        {{
            "source_paragraph_ids": ["P14", "P15"],
            "action": "consolidate",
            "section_name": "Professional Experience",
            "rewritten_text": "Combined paragraph text",
            "matched_requirements": ["R004"]
        }}
    ],
    "changes_summary": [
        "Brief explanation of editorial decisions"
    ]
}}

IMPORTANT:
- The example IDs above are illustrative. Use only IDs from the supplied context.
- Account for every source paragraph exactly once.
- Do not include header or personal contact information.
- The original profile paragraph should not be returned as a normal paragraph
  because its information is represented by professional_summary.
- Use the original section headings and paragraph order as structural guidance.
- Only include relevant content in the final resume.
"""
    logger.info("Sending resume tailoring request to Groq.")

    response = generate_response(
        system_prompt=system_prompt,
        user_prompt=user_prompt
    )

    logger.info(
        "Groq response received. Summary length=%s, tailored paragraphs=%s, changes=%s",
        len(response.get("professional_summary") or ""),
        len(response.get("paragraph_decisions", [])),
        len(response.get("changes_summary", []))
    )

    validated_response = RIEngineResponse.model_validate(response)

    decisions = validated_response.paragraph_decisions

    returned_ids = [
        paragraph_id
        for decision in decisions
        for paragraph_id in decision.source_paragraph_ids
    ]

    if len(returned_ids) != len(set(returned_ids)):
        raise ValueError("RIE returned duplicate paragraph IDs.")

    returned_id_set = set(returned_ids)

    missing_ids = available_paragraph_ids - returned_id_set
    invalid_ids = returned_id_set - available_paragraph_ids

    if missing_ids:
        raise ValueError(
            f"RIE omitted paragraph IDs: {sorted(missing_ids)}"
        )

    if invalid_ids:
        raise ValueError(
            f"RIE returned unknown paragraph IDs: {sorted(invalid_ids)}"
        )

    for decision in decisions:

        if not decision.source_paragraph_ids:
            raise ValueError("RIE returned a decision without source paragraph IDs.")

        if decision.action == "consolidate":
            if len(decision.source_paragraph_ids) < 2:
                raise ValueError("Consolidation requires at least two source paragraphs.")

        elif len(decision.source_paragraph_ids) != 1:
            raise ValueError(
                f"Action '{decision.action}' must reference exactly one paragraph."
            )

        if decision.action == "remove":
            if decision.section_name is not None or decision.rewritten_text is not None:
                raise ValueError("Removed paragraphs must have null section and text.")

        elif decision.action == "keep":
            if not decision.section_name or decision.rewritten_text is not None:
                raise ValueError("Invalid keep decision.")

        elif decision.action in {"rewrite", "consolidate"}:
            if not decision.section_name or not decision.rewritten_text:
                raise ValueError(f"Invalid {decision.action} decision.")

    logger.info(
        "RIE validation completed. Decisions=%s, removed=%s",
        len(decisions),
        sum(d.action == "remove" for d in decisions)
    )

    logger.info(
        "Resume Intelligence Engine completed successfully for resume_id=%s",
        resume_id
    )

    return validated_response.model_dump()