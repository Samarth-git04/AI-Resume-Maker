import json

from backend.services.context_builder import build_ai_context


RESUME_ID = 1

JOB_DESCRIPTION = """
Data Analyst

Required Skills:
- Strong experience with Python and SQL.
- Proficiency in Power BI and Tableau.
- Experience with data cleaning and manipulation.

Responsibilities:
- Develop dashboards and reports.
- Analyze datasets and identify trends.
- Communicate insights to stakeholders.

Preferred Qualifications:
- Experience with AWS.
- Knowledge of machine learning.
"""


def test_context_builder():

    print("\n--- Building AI Context ---")

    ai_context = build_ai_context(
        RESUME_ID,
        JOB_DESCRIPTION
    )

    assert isinstance(ai_context, dict)

    assert "job_requirements" in ai_context
    assert "resume_paragraphs" in ai_context
    assert "resume_formatting" in ai_context

    requirements = ai_context["job_requirements"]
    paragraphs = ai_context["resume_paragraphs"]
    formatting = ai_context["resume_formatting"]

    assert requirements
    assert paragraphs

    paragraph_ids = [
        paragraph["paragraph_id"]
        for paragraph in paragraphs
    ]

    assert len(paragraph_ids) == len(set(paragraph_ids))

    for paragraph in paragraphs:
        assert paragraph["text"]
        assert "matched_requirements" in paragraph

    assert "formats" in formatting
    assert "paragraphs" in formatting

    formatting_ids = {
        paragraph["id"]
        for paragraph in formatting["paragraphs"]
    }

    assert formatting_ids.issubset(set(paragraph_ids))

    print("\n--- Test Results ---")

    print("Requirements:", len(requirements))
    print("Unique paragraphs:", len(paragraphs))
    print("Formatting records:", len(formatting["paragraphs"]))
    print("Format definitions:", len(formatting["formats"]))

    print("\n--- AI Context ---")

    print(
        json.dumps(
            ai_context,
            indent=2,
            ensure_ascii=False
        )
    )

    serialized_context = json.dumps(
        ai_context,
        ensure_ascii=False
    )

    print("Context characters:", len(serialized_context))

    print("\nContext builder test passed.")


if __name__ == "__main__":
    test_context_builder()