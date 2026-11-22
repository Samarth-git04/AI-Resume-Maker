import unittest

from backend.services.jd_analyzer import (
    clean_text,
    detect_section,
    get_priority,
    classify_requirement,
    extract_requirements,
    TOP_K
)


class TestJDAnalyzer(unittest.TestCase):

    def test_clean_text(self):
        text = "  Python\u00a0and   SQL  "
        self.assertEqual(clean_text(text), "Python and SQL")

    def test_section_detection(self):
        self.assertEqual(
            detect_section("Required Skills:"),
            {
                "category": "technical_skills",
                "priority": "required"
            }
        )

        self.assertEqual(
            detect_section("Preferred Qualifications"),
            {
                "category": "qualifications",
                "priority": "preferred"
            }
        )

        self.assertIsNone(detect_section("Some random heading"))

    def test_priority_detection(self):
        self.assertEqual(get_priority("Python is required."), "required")
        self.assertEqual(get_priority("Python is preferred."), "preferred")
        self.assertEqual(get_priority("Python is not required."), "not_required")
        self.assertEqual(get_priority("Python experience."), "unspecified")

    def test_priority_inheritance(self):
        self.assertEqual(
            get_priority("Strong Python skills.", "required"),
            "required"
        )

        self.assertEqual(
            get_priority("Python experience.", "preferred"),
            "preferred"
        )

    def test_explicit_priority_overrides_inheritance(self):
        self.assertEqual(
            get_priority("Python is preferred.", "required"),
            "preferred"
        )

        self.assertEqual(
            get_priority("Python is not required.", "required"),
            "not_required"
        )

    def test_requirement_classification(self):
        self.assertIn(
            "technical_skills",
            classify_requirement("Strong Python and SQL skills are required.")
        )

        self.assertIn(
            "responsibilities",
            classify_requirement("You will develop automated data pipelines.")
        )

        self.assertIn(
            "qualifications",
            classify_requirement("A Bachelor's degree is preferred.")
        )

        self.assertIn(
            "experience",
            classify_requirement("Candidates need 2 years of experience.")
        )

        self.assertIn(
            "soft_skills",
            classify_requirement("Excellent communication and teamwork skills.")
        )

    def test_complete_extraction(self):
        job_description = """
        Requirements

        Required Skills:
        - Strong Python and SQL skills are required.
        - Experience with Power BI.

        Preferred Skills:
        - Knowledge of Tableau.
        - Excellent communication and teamwork skills.

        Responsibilities:
        - Develop automated data pipelines.
        - Build dashboards using Power BI.

        Required Qualifications:
        - A Bachelor's degree in Computer Science is required.

        Experience:
        - Candidates should have 2 years of professional experience.
        - Knowledge of AWS is not required.
        """

        requirements = extract_requirements(job_description)

        self.assertEqual(len(requirements), 9)

        expected = {
            "Strong Python and SQL skills are required.": "required",
            "Experience with Power BI.": "required",
            "Knowledge of Tableau.": "preferred",
            "Excellent communication and teamwork skills.": "preferred",
            "Develop automated data pipelines.": "unspecified",
            "Build dashboards using Power BI.": "unspecified",
            "A Bachelor's degree in Computer Science is required.": "required",
            "Candidates should have 2 years of professional experience.": "required",
            "Knowledge of AWS is not required.": "not_required"
        }

        extracted_texts = {
            requirement["text"]: requirement
            for requirement in requirements
        }

        for text, priority in expected.items():
            self.assertIn(text, extracted_texts)
            self.assertEqual(
                extracted_texts[text]["priority"],
                priority,
                msg=f"Incorrect priority for: {text}"
            )

        for requirement in requirements:
            self.assertTrue(requirement["requirement_id"])
            self.assertIsInstance(requirement["categories"], list)
            self.assertTrue(requirement["categories"])

        self.assertEqual(
            [r["requirement_id"] for r in requirements],
            [f"R{i:03d}" for i in range(1, 10)]
        )

    def test_empty_or_invalid_input(self):
        for value in ["", "   ", None, 123]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    extract_requirements(value)

    def test_top_k(self):
        self.assertEqual(TOP_K, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)