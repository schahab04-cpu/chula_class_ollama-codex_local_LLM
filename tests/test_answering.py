import json
import unittest
from unittest.mock import patch

from src.answering import answer


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{"file_id": "abc--notes.txt", "name": "notes.txt",
                         "location": "Paragraph 1",
                         "text": "Prompt engineering is writing effective instructions. Start simple, then refine."}]

    @patch("src.answering.ollama")
    def test_explanations_and_spelling_mistakes_are_not_lexically_rejected(self, ollama):
        explanation = "It means designing clear instructions for a model. Begin with a simple prompt and improve it."
        ollama.return_value = {"message": {"content": json.dumps({
            "answer": explanation, "sources": [1]})}}
        text, citations = answer("What can you tell me about prompt engeneering", self.sources, "gemma3:1b")
        self.assertEqual(text, explanation)
        self.assertEqual(citations[0]["quote"], self.sources[0]["text"])
        payload = ollama.call_args.args[1]
        self.assertEqual(payload["model"], "gemma3:1b")
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertIn("engeneering", payload["messages"][-1]["content"])

    @patch("src.answering.ollama")
    def test_partial_answer_is_preserved(self, ollama):
        partial = "The notes recommend starting simple and refining. They do not give a price."
        ollama.return_value = {"message": {"content": json.dumps({"answer": partial, "sources": [1]})}}
        self.assertEqual(answer("Explain prompting and its price", self.sources, "gemma3:1b")[0], partial)

    @patch("src.answering.ollama")
    def test_uncovered_topic_preserves_model_explanation_without_citations(self, ollama):
        missing = "These notes discuss prompting, but do not cover the launch budget."
        ollama.return_value = {"message": {"content": json.dumps({"answer": missing, "sources": []})}}
        self.assertEqual(answer("Launch budget?", self.sources, "gemma3:1b"), (missing, []))

    @patch("src.answering.ollama")
    def test_invalid_output_and_fabricated_references_are_errors(self, ollama):
        for content in ('not json', '{}', 'null',
                        '{"answer":"text","sources":[9]}',
                        '{"answer":"text","sources":[true]}',
                        '{"answer":"text","sources":"1"}',
                        '{"answer":" ","sources":[]}'):
            with self.subTest(content=content):
                ollama.return_value = {"message": {"content": content}}
                with self.assertRaises(ValueError):
                    answer("prompting", self.sources, "gemma3:1b")

    @patch("src.answering.ollama")
    def test_source_ids_are_deduplicated_and_resolved_by_server(self, ollama):
        self.sources.append({**self.sources[0], "location": "Paragraph 2"})
        ollama.return_value = {"message": {"content": '{"answer":"Useful explanation","sources":[2,2]}'}}
        _, citations = answer("prompting", self.sources, "gemma3:1b")
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["location"], "Paragraph 2")

    @patch("src.answering.ollama")
    def test_empty_library_explains_next_step_without_calling_model(self, ollama):
        text, citations = answer("prompting", [], "gemma3:1b")
        self.assertIn("Upload", text)
        self.assertEqual(citations, [])
        ollama.assert_not_called()

    @patch("src.answering.ollama")
    def test_invented_figures_are_not_displayed_with_real_citations(self, ollama):
        ollama.return_value = {"message": {"content": json.dumps({
            "answer": "The project costs 150,000 euros.", "sources": [1]})}}
        text, citations = answer("How much does the project cost?", self.sources, "gemma3:1b")
        self.assertNotIn("150,000", text)
        self.assertIn("do not establish", text)
        self.assertEqual(len(citations), 1)

    @patch("src.answering.ollama")
    def test_supported_numbers_and_list_markers_are_preserved(self, ollama):
        self.sources[0]["text"] = "The launch date is 15 June 2027. The budget is 150,000 euros."
        explanation = "1. Launch: 15 June 2027.\n2. Budget: 150000 euros."
        ollama.return_value = {"message": {"content": json.dumps({
            "answer": explanation, "sources": [1]})}}
        self.assertEqual(answer("Date and budget?", self.sources, "gemma3:1b")[0], explanation)
