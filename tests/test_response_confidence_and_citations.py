import unittest

from webapp.app.analyzer import _compute_answer_confidence, _extract_citations_from_rag


class TestResponseConfidenceAndCitations(unittest.TestCase):
    def test_extract_citations_prefers_existing_citation(self):
        rag = {
            "hits": [
                {"citation": "doc1.txt#row4", "file": "doc1.txt", "row_number": 4},
                {"citation": "doc1.txt#row4", "file": "doc1.txt", "row_number": 4},
                {"file": "doc2.txt", "row_number": 9},
            ]
        }
        cites = _extract_citations_from_rag(rag)
        self.assertEqual(cites, ["doc1.txt#row4", "doc2.txt#row9"])

    def test_extract_citations_handles_missing_values(self):
        rag = {"hits": [{"file": "", "row_number": None}, {}]}
        cites = _extract_citations_from_rag(rag)
        self.assertEqual(cites, [])

    def test_confidence_high_with_structured_and_cited_rag(self):
        conf = _compute_answer_confidence(
            workflow_result={"k": 1},
            rag_evidence={"hits": [{"citation": "a#row1"}]},
            clarification=None,
            citations=["a#row1"],
        )
        self.assertEqual(conf["level"], "High")

    def test_confidence_medium_with_partial_evidence(self):
        conf = _compute_answer_confidence(
            workflow_result={"k": 1},
            rag_evidence={"hits": [{"citation": ""}]},
            clarification=None,
            citations=[],
        )
        self.assertEqual(conf["level"], "Medium")

    def test_confidence_low_with_clarification(self):
        conf = _compute_answer_confidence(
            workflow_result={"k": 1},
            rag_evidence=None,
            clarification={"missing_slot": "item"},
            citations=[],
        )
        self.assertEqual(conf["level"], "Low")


if __name__ == "__main__":
    unittest.main()
