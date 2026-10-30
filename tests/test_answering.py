import json
import unittest
from unittest.mock import patch

from src.answering import MIN_DOCUMENT_COSINE, answer, general_answer, is_document_question, library_response


def responses(answer_text, passages=(1,)):
    """Evidence selection reply followed by the answer writer's reply."""
    return [{"message": {"content": json.dumps({"passages": list(passages)})}},
            {"message": {"content": json.dumps({"answer": answer_text})}}]


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{"file_id": "abc--notes.txt", "name": "notes.txt",
                         "location": "Paragraph 1",
                         "text": "Prompt engineering is writing effective instructions. Start simple, then refine."}]

    @patch("src.answering.ollama")
    def test_explanations_and_spelling_mistakes_are_not_lexically_rejected(self, ollama):
        explanation = "It means writing effective instructions for a model. Start simple and refine it."
        ollama.side_effect = responses(explanation)
        text, citations = answer("What can you tell me about prompt engeneering", self.sources, "qwen3:1.7b")
        self.assertEqual(text, explanation)
        self.assertEqual(citations[0]["quote"], self.sources[0]["text"])
        payload = ollama.call_args.args[1]
        self.assertEqual(payload["model"], "qwen3:1.7b")
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertIn("engeneering", payload["messages"][-1]["content"])

    @patch("src.answering.ollama")
    def test_partial_answer_is_preserved(self, ollama):
        partial = "The notes recommend starting simple and refining. They do not give a price."
        ollama.side_effect = responses(partial)
        self.assertEqual(answer("Explain prompting and its price", self.sources, "qwen3:1.7b")[0], partial)

    @patch("src.answering.ollama")
    def test_uncovered_topic_preserves_model_explanation_without_citations(self, ollama):
        missing = "Nothing here covers the launch budget."
        ollama.side_effect = responses(missing)
        self.assertEqual(answer("Launch budget?", self.sources, "qwen3:1.7b"), (missing, []))

    @patch("src.answering.ollama")
    def test_no_selected_evidence_is_not_found(self, ollama):
        ollama.side_effect = responses("unused", passages=())
        text, citations = answer("Launch budget?", self.sources, "qwen3:1.7b")
        self.assertIn("couldn't find", text)
        self.assertEqual(citations, [])
        self.assertEqual(ollama.call_count, 1)

    @patch("src.answering.ollama")
    def test_invalid_answer_output_is_an_error(self, ollama):
        for content in ('not json', '{}', 'null', '{"answer":" "}', '{"answer":1}'):
            with self.subTest(content=content):
                ollama.side_effect = [responses("")[0], {"message": {"content": content}}]
                with self.assertRaises(ValueError):
                    answer("prompting", self.sources, "qwen3:1.7b")

    @patch("src.answering.ollama")
    def test_invalid_evidence_references_are_errors(self, ollama):
        for content in ('not json', '{}', '{"passages":[9]}', '{"passages":[true]}', '{"passages":"1"}'):
            with self.subTest(content=content):
                ollama.side_effect = [{"message": {"content": content}}]
                with self.assertRaises(ValueError):
                    answer("prompting", self.sources, "qwen3:1.7b")

    @patch("src.answering.ollama")
    def test_selected_ids_are_deduplicated_and_resolved_by_server(self, ollama):
        self.sources.append({**self.sources[0], "location": "Paragraph 2"})
        ollama.side_effect = responses("Prompt engineering means writing instructions.", passages=(2, 2))
        _, citations = answer("prompting", self.sources, "qwen3:1.7b")
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["location"], "Paragraph 2")

    @patch("src.answering.ollama")
    def test_empty_library_explains_next_step_without_calling_model(self, ollama):
        text, citations = answer("prompting", [], "qwen3:1.7b")
        self.assertIn("Upload", text)
        self.assertEqual(citations, [])
        ollama.assert_not_called()

    @patch("src.answering.ollama")
    def test_invented_figures_are_not_displayed_with_real_citations(self, ollama):
        ollama.side_effect = responses("Writing effective instructions costs 150,000 euros.")
        text, citations = answer("How much does prompting cost?", self.sources, "qwen3:1.7b")
        self.assertNotIn("150,000", text)
        self.assertIn("do not establish", text)
        self.assertEqual(len(citations), 1)

    @patch("src.answering.ollama")
    def test_supported_numbers_and_list_markers_are_preserved(self, ollama):
        self.sources[0]["text"] = "The launch date is 15 June 2027. The budget is 150,000 euros."
        explanation = "1. Launch date: 15 June 2027.\n2. Budget: 150000 euros."
        ollama.side_effect = responses(explanation)
        self.assertEqual(answer("Date and budget?", self.sources, "qwen3:1.7b")[0], explanation)


    @patch("src.answering.ollama")
    def test_inline_list_markers_are_not_figures(self, ollama):
        self.sources[0]["text"] = "Plans: protection plans and commercialization plans."
        explanation = "The plans are: 1. Protection plans. 2. Commercialization plans."
        ollama.side_effect = responses(explanation)
        self.assertEqual(answer("Which plans?", self.sources, "qwen3:1.7b")[0], explanation)

    @patch("src.answering.ollama")
    def test_source_locations_are_not_figures(self, ollama):
        explanation = "Writing effective instructions is covered in Paragraph 1."
        ollama.side_effect = responses(explanation)
        self.assertEqual(answer("Where?", self.sources, "qwen3:1.7b")[0], explanation)

    @patch("src.answering.ollama")
    def test_full_years_match_shortened_dates(self, ollama):
        self.sources[0]["text"] = "10/15/26 Final presentation on 12 Nov."
        explanation = "The final presentation is on 12 November 2026."
        ollama.side_effect = responses(explanation)
        self.assertEqual(answer("When is the presentation?", self.sources, "qwen3:1.7b")[0], explanation)
        ollama.side_effect = responses("The final presentation is on 12 November 2031.")
        self.assertIn("do not establish", answer("When is it?", self.sources, "qwen3:1.7b")[0])

    @patch("src.answering.ollama")
    def test_magnitudes_and_filenames_match_cited_text(self, ollama):
        self.sources[0]["text"] = "Writing instructions risks a maximum fine of 20M."
        self.sources[0]["name"] = "Session_8-908488.pdf"
        explanation = "Writing instructions risks a fine of 20 million, as Session_8-908488.pdf says."
        ollama.side_effect = responses(explanation)
        self.assertEqual(answer("Fine?", self.sources, "qwen3:1.7b")[0], explanation)
        ollama.side_effect = responses("Writing instructions risks a fine of 30 million.")
        self.assertIn("do not establish", answer("Fine?", self.sources, "qwen3:1.7b")[0])

    @patch("src.answering.ollama")
    def test_figures_ending_a_sentence_are_still_checked(self, ollama):
        ollama.side_effect = responses("Writing effective instructions costs 150. Start simple.")
        self.assertIn("do not establish", answer("Cost?", self.sources, "qwen3:1.7b")[0])


class RoutingTests(unittest.TestCase):
    def sources(self, score):
        return [{"score": 0.1}, {"score": score}]

    def test_similarity_threshold_selects_documents(self):
        self.assertTrue(is_document_question("What does the CCPA do?", self.sources(MIN_DOCUMENT_COSINE)))
        self.assertFalse(is_document_question("What is the capital of France?", self.sources(0.51)))

    def test_explicit_document_references_override_low_similarity(self):
        for question in ("can you summarize session 8?", "summarize the uploaded documents",
                         "What do my documents say about breaches?", "explain the lecture slides"):
            with self.subTest(question=question):
                self.assertTrue(is_document_question(question, self.sources(0.5)))

    def test_questions_about_the_users_own_context_use_documents(self):
        for question in ("What is the final project about?", "what is the grading?",
                         "who is the instructor?", "what is the course about?",
                         "how many sessions are there?", "what is due next week?",
                         "tell me about the assignment", "how long is the final paper?"):
            with self.subTest(question=question):
                self.assertTrue(is_document_question(question, self.sources(0.55)))

    def test_generic_mentions_of_files_stay_general(self):
        for question in ("How do I read a file in Python?", "What is a PDF?",
                         "What is the best project management software?",
                         "How do I write a good final exam essay?", "What is a class in Python?",
                         "How do I pass an exam?", "how do I give a good presentation?"):
            with self.subTest(question=question):
                self.assertFalse(is_document_question(question, self.sources(0.5)))

    def test_empty_library_is_never_a_document_question(self):
        self.assertFalse(is_document_question("summarize the uploaded documents", []))


class LibraryResponseTests(unittest.TestCase):
    def test_lists_real_names_for_questions_about_the_library(self):
        for question in ("What files do you have access to?", "which documents do you have",
                         "What documents are uploaded?", "list my files", "Show me all the documents.",
                         "Do you have access to my files?", "do you have any documents?",
                         "What are the papers in my document collection?", "what papers do i have?",
                         "What papers are in my collection?", "what are my papers", "list my papers",
                         "do I have any papers?", "Which documents are in the library?"):
            with self.subTest(question=question):
                self.assertIn("notes.pdf", library_response(question, ["notes.pdf"]))

    def test_empty_library_says_so(self):
        self.assertIn("No documents", library_response("What files do you have?", []))

    def test_questions_about_content_are_not_library_questions(self):
        for question in ("What documents discuss the GDPR?", "What files are needed for a visa?",
                         "How do I list files in Python?", "What do my documents say about fines?",
                         "What papers discuss data breaches?", "how long is the final paper?",
                         "What are the papers about?"):
            with self.subTest(question=question):
                self.assertIsNone(library_response(question, ["notes.pdf"]))


class GeneralAnswerTests(unittest.TestCase):
    messages = [{"role": "user", "content": "Capital of France?"},
                {"role": "assistant", "content": "Paris."},
                {"role": "user", "content": "And of Germany?"}]

    @patch("src.answering.ollama")
    def test_sends_history_without_json_schema(self, ollama):
        ollama.return_value = {"message": {"content": " Berlin. "}}
        self.assertEqual(general_answer(self.messages, "qwen3:1.7b"), "Berlin.")
        payload = ollama.call_args.args[1]
        self.assertNotIn("format", payload)
        self.assertFalse(payload["think"])
        self.assertEqual(payload["messages"][1:], self.messages)

    @patch("src.answering.ollama")
    def test_numbers_are_not_rejected(self, ollama):
        ollama.return_value = {"message": {"content": "12 times 12 is 144."}}
        self.assertIn("144", general_answer(self.messages, "qwen3:1.7b"))

    @patch("src.answering.ollama")
    def test_empty_or_malformed_output_is_an_error(self, ollama):
        for result in ({"message": {"content": " "}}, {"message": {}}, {}):
            with self.subTest(result=result):
                ollama.return_value = result
                with self.assertRaises(ValueError):
                    general_answer(self.messages, "qwen3:1.7b")
