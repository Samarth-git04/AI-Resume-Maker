import logging
import re
import json
from typing import Any

from sqlalchemy.orm import Session

from backend.services.context_builder import build_ai_context
from backend.services.llm_service import generate_response
from backend.services.resume_structure import build_resume_structure
from backend.services.resume_text import clean_resume_text, comparison_text


logger = logging.getLogger(__name__)


PROJECT_REQUIREMENT_WEIGHTS = {
    "required": 1.5,
    "preferred": 1.15,
    "unspecified": 1.0,
    "not_required": 0.0,
}


def _numbers(text: str) -> set:
    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", text or ""))


def _safe_rewrite(original: str, proposed: Any) -> str | None:
    if not isinstance(proposed, str) or not proposed.strip():
        return None

    proposed = re.sub(r"\s+", " ", proposed).strip()

    if len(proposed) > max(450, len(original) * 2.5):
        return None

    if _numbers(proposed) - _numbers(original):
        return None

    return proposed


def _score_project(
    project: dict,
    paragraph_lookup: dict,
    requirements: list,
) -> float:
    """
    Score a project using its best FAISS similarity score for each
    job requirement.

    Required requirements receive the highest weight. Preferred
    requirements receive a lower weight. Not-required requirements
    do not contribute to the score.

    Missing requirement matches receive a score of zero.
    """

    requirement_scores = {}

    for paragraph_id in project["paragraph_ids"]:
        paragraph = paragraph_lookup.get(paragraph_id, {})

        for match in paragraph.get("matched_requirements", []):
            requirement_id = match.get("requirement_id")
            score = match.get("score")

            if (
                not requirement_id
                or not isinstance(score, (int, float))
            ):
                continue

            score = float(score)

            current_score = requirement_scores.get(requirement_id)

            if current_score is None or score > current_score:
                requirement_scores[requirement_id] = score

    weighted_score = 0.0
    total_weight = 0.0
    covered_weight = 0.0

    for requirement in requirements:
        requirement_id = requirement.get("requirement_id")
        priority = requirement.get("priority", "unspecified")

        weight = PROJECT_REQUIREMENT_WEIGHTS.get(
            priority,
            1.0,
        )

        if weight == 0:
            continue

        total_weight += weight

        score = requirement_scores.get(requirement_id, 0.0)

        weighted_score += score * weight

        if requirement_id in requirement_scores:
            covered_weight += weight

    if total_weight == 0:
        return 0.0

    average_similarity = weighted_score / total_weight
    requirement_coverage = covered_weight / total_weight

    # Similarity determines relevance. Coverage rewards projects
    # that match a wider range of JD requirements.
    return average_similarity + (0.10 * requirement_coverage)


def _rank_projects(
    projects: list,
    paragraph_lookup: dict,
    requirements: list,
) -> list:
    """
    Rank projects deterministically.

    The AI receives only the three highest-ranked projects.
    Ties are resolved using the original project title ID.
    """

    ranked = []

    for project in projects:
        score = _score_project(
            project,
            paragraph_lookup,
            requirements,
        )

        ranked.append({
            "project": project,
            "score": score,
        })

    ranked.sort(
        key=lambda item: (
            -item["score"],
            item["project"]["title_id"],
        )
    )

    return ranked


def _find_key_achievements(records: list) -> list:
    achievement_heading_found = False
    achievement_ids = []

    for record in records:
        section = record.get("section")
        role = record.get("role")
        text = clean_resume_text(record.get("text", ""))

        if not text:
            continue

        if section != "HIGHLIGHTS":
            if achievement_heading_found:
                break
            continue

        normalized = re.sub(
            r"[^a-z0-9]+",
            " ",
            comparison_text(text),
        ).strip()

        if normalized == "key achievements":
            achievement_heading_found = True
            continue

        if not achievement_heading_found:
            continue

        if role in {"subheading", "section_heading"}:
            break

        if role in {"bullet", "content"}:
            achievement_ids.append(record["id"])

    return achievement_ids


def _experience_context(records: list) -> tuple[list, list, str]:
    experience_records = [
        record
        for record in records
        if record.get("section") == "EXPERIENCE"
    ]

    company_candidates = []

    for record in experience_records:
        if record.get("role") != "subheading":
            continue

        candidate = clean_resume_text(record.get("text", ""))

        if candidate and candidate not in company_candidates:
            company_candidates.append(candidate)

    experience_text = "\n".join(
        clean_resume_text(record.get("text", ""))
        for record in experience_records
        if clean_resume_text(record.get("text", ""))
    )

    editable_experience = [
        {
            "id": record["id"],
            "text": record["text"],
            "role": record["role"],
        }
        for record in experience_records
        if record.get("role") in {"bullet", "content"}
    ]

    return editable_experience, company_candidates, experience_text


def _company_is_supported(
    company: str,
    company_candidates: list,
    experience_text: str,
    original_achievement: str,
) -> bool:
    company = clean_resume_text(company)

    if not company:
        return False

    company_key = comparison_text(company)

    if company_candidates:
        if any(
            company_key in comparison_text(candidate)
            for candidate in company_candidates
        ):
            return True

    if company_key in comparison_text(experience_text):
        return True

    prefix_match = re.match(
        r"^\s*(.{2,70}?)\s*:\s*.+$",
        original_achievement,
    )

    if (
        prefix_match
        and company_key == comparison_text(prefix_match.group(1))
    ):
        return True

    return False


def _achievement_body(
    original: str,
    proposed: Any,
    company: str,
) -> str | None:
    if not isinstance(proposed, str) or not proposed.strip():
        return None

    proposed = clean_resume_text(proposed)

    prefix = re.match(
        rf"^{re.escape(company)}\s*:\s*(.*)$",
        proposed,
        flags=re.IGNORECASE,
    )

    if prefix:
        proposed = prefix.group(1).strip()

    if not proposed:
        return None

    return _safe_rewrite(original, proposed)


def _normalise_achievements(
    proposed: Any,
    achievement_ids: list,
    paragraph_lookup: dict,
    company_candidates: list,
    experience_text: str,
) -> list:
    """
    Validate the three achievements selected by the AI.

    There is intentionally no Python fallback. The AI must select
    three distinct source achievements and provide supported employers.
    """

    if not isinstance(proposed, list) or len(proposed) != 3:
        return []

    valid_ids = set(achievement_ids)
    selected = []
    seen_ids = set()

    for item in proposed:
        if not isinstance(item, dict):
            return []

        paragraph_id = item.get("source_paragraph_id")
        company = clean_resume_text(item.get("company", ""))

        if (
            paragraph_id not in valid_ids
            or paragraph_id in seen_ids
        ):
            return []

        original = paragraph_lookup[paragraph_id]["text"]

        if not _company_is_supported(
            company,
            company_candidates,
            experience_text,
            original,
        ):
            return []

        body = _achievement_body(
            original,
            item.get("what_i_did"),
            company,
        )

        if body is None:
            return []

        seen_ids.add(paragraph_id)

        selected.append({
            "source_paragraph_id": paragraph_id,
            "company": company,
            "text": f"{company}: {body}",
        })

    return selected if len(selected) == 3 else []


def _normalise_model_decisions(
    model_decisions: Any,
    records: list,
    paragraph_lookup: dict,
    requirements: list,
    allowed_ids: set,
) -> dict:
    """
    Validate AI decisions.

    The AI may keep, rewrite or remove supplied paragraphs.
    Experience bullets are no longer protected from removal.
    """

    requirement_ids = {
        item["requirement_id"]
        for item in requirements
    }

    result = {}

    if not isinstance(model_decisions, list):
        return result

    for decision in model_decisions:
        if not isinstance(decision, dict):
            continue

        ids = decision.get("source_paragraph_ids")

        if not isinstance(ids, list) or len(ids) != 1:
            continue

        paragraph_id = ids[0]

        if (
            paragraph_id not in allowed_ids
            or paragraph_id in result
        ):
            continue

        source = paragraph_lookup[paragraph_id]
        action = decision.get("action")

        if action not in {"keep", "rewrite", "remove"}:
            continue

        matched = decision.get("matched_requirements", [])

        if not isinstance(matched, list):
            matched = []

        matched = [
            item
            for item in matched
            if item in requirement_ids
        ]

        if action == "rewrite":
            rewritten = _safe_rewrite(
                source["text"],
                decision.get("rewritten_text"),
            )

            if rewritten is None:
                continue

        else:
            rewritten = None

        result[paragraph_id] = {
            "source_paragraph_ids": [paragraph_id],
            "action": action,
            "section_name": source.get("section"),
            "rewritten_text": rewritten,
            "matched_requirements": matched,
        }

    return result


def run_ri_engine(
    db: Session,
    resume_id: int,
    job_description: str,
) -> dict:

    if (
        not isinstance(job_description, str)
        or not job_description.strip()
    ):
        raise ValueError("Job description cannot be empty.")

    context = build_ai_context(
        db,
        resume_id,
        job_description,
    )

    paragraphs = context["resume_paragraphs"]
    formatting = context["resume_formatting"]
    requirements = context["job_requirements"]

    if len(paragraphs) < 4:
        raise ValueError(
            "The uploaded resume does not contain enough content."
        )

    structure = build_resume_structure(
        paragraphs,
        formatting,
    )

    records = structure["records"]
    projects = structure["projects"]
    profile_id = structure["profile_id"]

    if len(projects) < 3:
        raise ValueError(
            "At least three identifiable project titles are required; "
            f"found {len(projects)}."
        )

    paragraph_lookup = {
        item["paragraph_id"]: item
        for item in paragraphs
    }

    header_ids = {
        item["id"]
        for item in records
        if item["role"] == "header"
    }

    editable_ids = structure["editable_ids"] - header_ids

    if profile_id:
        editable_ids.discard(profile_id)

    achievement_ids = _find_key_achievements(records)

    if len(achievement_ids) < 3:
        raise ValueError(
            "At least three bullet points are required under "
            "HIGHLIGHTS > KEY ACHIEVEMENTS."
        )

    experience_paragraphs, company_candidates, experience_text = (
        _experience_context(records)
    )

    achievement_id_set = set(achievement_ids)

    # ---------------------------------------------------------
    # 1. Score projects in Python and select the top three.
    # ---------------------------------------------------------

    ranked_projects = _rank_projects(
        projects,
        paragraph_lookup,
        requirements,
    )

    selected_project_entries = ranked_projects[:3]

    selected_projects = [
        item["project"]
        for item in selected_project_entries
    ]

    selected_project_ids = [
        project["title_id"]
        for project in selected_projects
    ]

    selected_project_paragraph_ids = {
        paragraph_id
        for project in selected_projects
        for paragraph_id in project["paragraph_ids"]
    }

    for item in selected_project_entries:
        logger.info(
            "Project relevance score. resume_id=%s project=%s score=%.4f",
            resume_id,
            item["project"]["title"],
            item["score"],
        )

    # ---------------------------------------------------------
    # 2. Build AI context using only the selected projects.
    # ---------------------------------------------------------

    project_payload = []

    for project in selected_projects:
        project_payload.append({
            "title_id": project["title_id"],
            "title": project["title"],
            "paragraphs": [
                {
                    "id": paragraph_id,
                    "text": paragraph_lookup[paragraph_id]["text"],
                    "matched_requirements": paragraph_lookup[
                        paragraph_id
                    ]["matched_requirements"],
                }
                for paragraph_id in project["paragraph_ids"]
                if paragraph_id != project["title_id"]
            ],
        })

    editable_payload = [
        {
            "id": item["id"],
            "section": item["section"],
            "text": item["text"],
            "matched_requirements": paragraph_lookup[
                item["id"]
            ]["matched_requirements"],
        }
        for item in records
        if (
            item["id"] in editable_ids
            and item["id"] not in achievement_id_set
            and item["role"] != "project_content"
        )
    ]

    # Only descriptions belonging to the selected three projects
    # are supplied for AI editing.
    project_content_payload = [
        {
            "id": item["id"],
            "section": item["section"],
            "text": item["text"],
            "matched_requirements": paragraph_lookup[
                item["id"]
            ]["matched_requirements"],
        }
        for item in records
        if (
            item["role"] == "project_content"
            and item["id"] in selected_project_paragraph_ids
        )
    ]

    achievement_payload = [
        {
            "id": paragraph_id,
            "text": paragraph_lookup[paragraph_id]["text"],
            "matched_requirements": paragraph_lookup[
                paragraph_id
            ]["matched_requirements"],
        }
        for paragraph_id in achievement_ids
    ]

    profile_text = (
        paragraph_lookup[profile_id]["text"]
        if profile_id and profile_id in paragraph_lookup
        else ""
    )

    # ---------------------------------------------------------
    # 3. AI instructions.
    # ---------------------------------------------------------

    system_prompt = """
You are a professional resume editor.

The supplied resume is the only source of candidate facts.
The supplied job description determines relevance and priority.

IMPORTANT: Do not invent facts, experience, employers, dates,
qualifications, tools, metrics, responsibilities or outcomes.

TASK 1 - PROFESSIONAL SUMMARY

Write a concise professional summary based on the original profile
and factual resume content.

Do not infer years of experience, seniority, qualifications,
metrics, tools or achievements.

TASK 2 - KEY ACHIEVEMENTS

Select EXACTLY THREE achievements from key_achievements.

You must make the selection yourself based on relevance to the
job description.

Do not select achievements based on their order in the resume.
Prioritise achievements that demonstrate the most relevant skills,
responsibilities, technical capabilities and outcomes.

Do not invent or combine separate achievements.

For each selected achievement:
- Return its original source paragraph ID.
- Return the exact employer/company name supported by the
  experience section.
- Return a concise what_i_did statement.
- Preserve the original achievement's factual meaning.
- Preserve every numerical claim.

The final format will be:
"Company: What I did"

Use a company name from company_candidates or an employer name
explicitly present in experience_text.

Never use a job title as the company name.

You must return three different source paragraph IDs.

TASK 3 - EXPERIENCE BULLETS

Review every supplied experience paragraph against the job description.

You may:
- Keep a bullet unchanged.
- Rewrite a bullet to improve relevance, clarity or impact.
- Remove a bullet if it is irrelevant, weak, repetitive or does
  not meaningfully support the target role.

Do NOT automatically retain every bullet.

Actively remove bullets that add little value for this particular JD.
Prioritise the strongest and most relevant responsibilities,
technical work and outcomes.

Do not remove every bullet belonging to an employer. Retain at least
the strongest relevant point for each employer where possible.

Do not change the factual meaning of retained bullets.

TASK 4 - PROJECT DESCRIPTIONS

The supplied project_groups contain the THREE projects already
selected by Python using JD relevance scores.

You must NOT select different projects.

Rewrite or remove project description paragraphs where doing so
improves relevance to the JD.

You may:
- Keep a project paragraph unchanged.
- Rewrite a project paragraph.
- Remove an irrelevant or repetitive project bullet.

Do not invent project details, technologies, metrics or outcomes.

Every project description paragraph supplied must receive exactly
one decision.

TASK 5 - OTHER EDITABLE PARAGRAPHS

Review every supplied editable paragraph.

Use keep, rewrite or remove according to its relevance and value
for the target job.

Do not remove factual information simply because it is not an exact
keyword match.

TASK 6 - FACTUAL AND FORMATTING RULES

- Preserve technical detail and all numerical claims.
- Never add new numbers, dates, percentages or quantities.
- Never invent employers, tools, responsibilities or outcomes.
- Never invent a skill because it appears in the job description.
- Do not create section names, headings, job titles, employer names
  or dates.
- Do not merge paragraphs.
- Do not return decisions for paragraph IDs that were not supplied.
- Use one source paragraph ID per decision.
- Do not return section_name.

Return one JSON object with exactly these keys:

{
  "professional_summary": "string",
  "selected_achievements": [
    {
      "source_paragraph_id": "P4",
      "company": "Exact employer name",
      "what_i_did": "Factual achievement statement"
    }
  ],
  "paragraph_decisions": [
    {
      "source_paragraph_ids": ["P5"],
      "action": "keep",
      "rewritten_text": null,
      "matched_requirements": ["R001"]
    }
  ],
  "changes_summary": ["short explanation"]
}

STRICT OUTPUT REQUIREMENTS

- Return exactly three selected_achievements.
- Use three distinct source paragraph IDs.
- Every editable paragraph ID supplied must have exactly one decision.
- Every project description paragraph supplied must have exactly one decision.
- Use one source paragraph ID per decision.
- For keep and remove, rewritten_text must be null.
- For rewrite, provide the rewritten text.
- For experience bullets, keep, rewrite and remove are all allowed.
- Do not return selected_project_ids. Python has already selected
  the projects.
- Do not add markdown or text outside the JSON object.
""".strip()

    user_payload = {
        "job_requirements": requirements,
        "original_profile": profile_text,
        "company_candidates": company_candidates,
        "experience_text": experience_text,
        "experience_paragraphs": experience_paragraphs,
        "key_achievements": achievement_payload,
        "editable_paragraphs": editable_payload,
        "project_groups": project_payload,
        "project_description_paragraphs": project_content_payload,
    }

    # ---------------------------------------------------------
    # 4. Generate AI decisions.
    # ---------------------------------------------------------

    response = generate_response(
        system_prompt=system_prompt,
        user_prompt=json.dumps(
            user_payload,
            ensure_ascii=False,
        ),
    )

    if not isinstance(response, dict):
        raise ValueError(
            "The resume editor returned an invalid response."
        )

    # ---------------------------------------------------------
    # 5. Validate AI-selected achievements.
    # ---------------------------------------------------------

    selected_achievements = _normalise_achievements(
        response.get("selected_achievements"),
        achievement_ids,
        paragraph_lookup,
        company_candidates,
        experience_text,
    )

    if len(selected_achievements) != 3:
        raise ValueError(
            "The AI did not return exactly three valid key achievements. "
            "Each achievement must reference a different original "
            "achievement and use an employer supported by the resume."
        )

    # ---------------------------------------------------------
    # 6. Validate the professional summary.
    # ---------------------------------------------------------

    summary = response.get("professional_summary")

    if not isinstance(summary, str) or not summary.strip():
        summary = profile_text

    else:
        summary = re.sub(
            r"\s+",
            " ",
            summary,
        ).strip()

        all_source_text = " ".join(
            item["text"]
            for item in paragraphs
        )

        if _numbers(summary) - _numbers(all_source_text):
            summary = profile_text

        if re.search(
            r"\b\d+\+?\s+years?\s+(?:of\s+)?experience\b",
            summary,
            re.I,
        ):
            if not re.search(
                r"\b\d+\+?\s+years?\s+(?:of\s+)?experience\b",
                all_source_text,
                re.I,
            ):
                summary = profile_text

        if len(summary.split()) > 65:
            summary = profile_text

    # ---------------------------------------------------------
    # 7. Validate paragraph decisions.
    # ---------------------------------------------------------

    required_decision_ids = {
        item["id"]
        for item in editable_payload
    } | {
        item["id"]
        for item in project_content_payload
    }

    model_decisions = _normalise_model_decisions(
        response.get("paragraph_decisions"),
        records,
        paragraph_lookup,
        requirements,
        required_decision_ids,
    )

    missing_decisions = (
        required_decision_ids - set(model_decisions)
    )

    if missing_decisions:
        raise ValueError(
            "The AI did not return a valid decision for every supplied "
            "editable paragraph. Missing paragraph IDs: "
            + ", ".join(sorted(missing_decisions))
        )

    # ---------------------------------------------------------
    # 8. Apply AI-selected achievements.
    # ---------------------------------------------------------

    achievement_lookup = {
        item["source_paragraph_id"]: item["text"]
        for item in selected_achievements
    }

    for paragraph_id in achievement_ids:
        if paragraph_id in achievement_lookup:
            achievement_text = achievement_lookup[paragraph_id]
            original_text = paragraph_lookup[paragraph_id]["text"]

            is_unchanged = (
                comparison_text(achievement_text)
                == comparison_text(original_text)
            )

            model_decisions[paragraph_id] = {
                "source_paragraph_ids": [paragraph_id],
                "action": "keep" if is_unchanged else "rewrite",
                "section_name": "HIGHLIGHTS",
                "rewritten_text": (
                    None if is_unchanged else achievement_text
                ),
                "matched_requirements": [
                    match["requirement_id"]
                    for match in paragraph_lookup[
                        paragraph_id
                    ]["matched_requirements"]
                    if "requirement_id" in match
                ],
            }

        else:
            model_decisions[paragraph_id] = {
                "source_paragraph_ids": [paragraph_id],
                "action": "remove",
                "section_name": "HIGHLIGHTS",
                "rewritten_text": None,
                "matched_requirements": [],
            }

    # ---------------------------------------------------------
    # 9. Build final paragraph decisions.
    # ---------------------------------------------------------

    decisions = []

    for item in records:
        paragraph_id = item["id"]

        if paragraph_id in header_ids or paragraph_id == profile_id:
            continue

        if paragraph_id in model_decisions and (
            paragraph_id in editable_ids
            or item["role"] == "project_content"
            or paragraph_id in achievement_id_set
        ):
            decisions.append(
                model_decisions[paragraph_id]
            )

        else:
            decisions.append({
                "source_paragraph_ids": [paragraph_id],
                "action": "keep",
                "section_name": item["section"],
                "rewritten_text": None,
                "matched_requirements": [
                    match["requirement_id"]
                    for match in paragraph_lookup[
                        paragraph_id
                    ]["matched_requirements"]
                    if "requirement_id" in match
                ],
            })

    # ---------------------------------------------------------
    # 10. Validate final paragraph mapping.
    # ---------------------------------------------------------

    expected_ids = {
        item["id"]
        for item in records
        if (
            item["id"] not in header_ids
            and item["id"] != profile_id
        )
    }

    returned_ids = [
        paragraph_id
        for decision in decisions
        for paragraph_id in decision["source_paragraph_ids"]
    ]

    if (
        len(returned_ids) != len(set(returned_ids))
        or set(returned_ids) != expected_ids
    ):
        raise ValueError(
            "Internal resume decision validation failed."
        )

    # ---------------------------------------------------------
    # 11. Clean changes summary.
    # ---------------------------------------------------------

    changes = response.get("changes_summary", [])

    if not isinstance(changes, list):
        changes = []

    changes = [
        str(item).strip()
        for item in changes
        if str(item).strip()
    ][:8]

    logger.info(
        "Resume tailoring complete. resume_id=%s "
        "source_paragraphs=%s selected_projects=%s "
        "selected_achievements=%s experience_bullets=%s "
        "removed_paragraphs=%s",
        resume_id,
        len(paragraphs),
        len(selected_project_ids),
        len(selected_achievements),
        len([
            item
            for item in experience_paragraphs
            if item["role"] == "bullet"
        ]),
        sum(
            1
            for decision in decisions
            if decision["action"] == "remove"
        ),
    )

    return {
        "professional_summary": summary,
        "selected_project_ids": selected_project_ids,
        "selected_achievement_ids": [
            item["source_paragraph_id"]
            for item in selected_achievements
        ],
        "paragraph_decisions": decisions,
        "changes_summary": changes,
    }