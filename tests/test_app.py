import re
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.app import MODEL, app, main
from src.rag import DocumentError, NOT_FOUND


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.messages = [{"role": "user", "content": "What is the launch date?"}]
        # The summary router is a model call; these tests cover the code-decided routes.
        router = patch("src.app.route_with_summaries", return_value=False)
        self.route_with_summaries = router.start()
        self.addCleanup(router.stop)

    @patch("src.app.ollama_service.missing_models", return_value=[])
    @patch("src.app.ollama_service.ensure_running", return_value=True)
    @patch("src.app.app.run")
    def test_startup_uses_only_localhost_port_5050(self, run, ensure_running, _):
        with patch("sys.argv", ["app.py"]):
            main()
        ensure_running.assert_called_once()
        run.assert_called_once_with(host="127.0.0.1", port=5050, debug=False)

    @patch("src.app.ollama_service.missing_models", return_value=["qwen3.5:9b"])
    @patch("src.app.ollama_service.ensure_running", return_value=True)
    @patch("src.app.app.run")
    def test_startup_names_missing_models(self, run, _, __):
        with patch("sys.argv", ["app.py"]), self.assertLogs(app.logger, level="WARNING") as logs:
            main()
        self.assertIn("ollama pull qwen3.5:9b", logs.output[0])
        run.assert_called_once()

    def test_page_and_assets(self):
        for path in ("/", "/static/quiz.js", "/static/chat.js", "/static/files.js", "/static/views.js", "/static/wisp.js", "/static/voice.js", "/static/style.css"):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="files-view"', html)
        self.assertIn('id="dropzone"', html)
        self.assertIn('id="preview-dialog"', html)
        # Voice is the page itself; chat and documents open in a panel over it.
        self.assertLess(html.index('id="voice-view"'), html.index('id="workspace"'))
        self.assertIn('id="voice-start"', html)

    def test_page_scripts_share_no_top_level_names(self):
        # Classic scripts share one global scope: a repeated let/const stops the later script loading.
        static = Path(__file__).resolve().parent.parent / "src" / "static"
        declared = [set(re.findall(r"^(?:let|const|(?:async )?function) +(\w+)",
                                   (static / name).read_text(encoding="utf-8"), re.M))
                    for name in ("chat.js", "files.js", "quiz.js", "voice.js", "wisp.js")]
        for index, names in enumerate(declared):
            for other in declared[index + 1:]:
                self.assertEqual(names & other, set())

    @patch("src.app.knowledge_base")
    @patch("src.app.answer")
    def test_answers_are_retrieved_from_latest_user_question(self, answer, kb):
        kb.return_value.retrieve.return_value = [{"score": 0.8}]
        answer.return_value = (NOT_FOUND, [])
        response = self.client.post("/api/chat", json={"messages": self.messages})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["message"]["content"], NOT_FOUND)
        self.assertEqual(response.json["mode"], "documents")
        kb.return_value.retrieve.assert_called_once_with("What is the launch date?")

    @patch("src.app.knowledge_base")
    @patch("src.app.answer")
    @patch("src.app.general_answer", return_value="Paris.")
    def test_unrelated_questions_get_a_general_answer_with_history(self, general, answer, kb):
        kb.return_value.retrieve.return_value = [{"score": 0.5}]
        history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"},
                   {"role": "user", "content": "Capital of France?"}]
        response = self.client.post("/api/chat", json={"messages": history})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["message"]["content"], "Paris.")
        self.assertEqual(response.json["sources"], [])
        self.assertEqual(response.json["mode"], "general")
        general.assert_called_once_with(history, "qwen3.5:9b")
        answer.assert_not_called()

    @patch("src.app.document_names", return_value=["Neutraceuticals.pdf"])
    @patch("src.app.knowledge_base")
    @patch("src.app.answer", return_value=("Supplements.", []))
    def test_naming_a_file_routes_to_documents_without_a_model_check(self, answer, kb, _):
        kb.return_value.retrieve.return_value = [{"score": 0.56}]
        for question in ("What does neutraceuticals.pdf hold?", "Summarize Neutraceuticals"):
            response = self.client.post("/api/chat", json={"messages": [{"role": "user", "content": question}]})
            self.assertEqual(response.json["mode"], "documents")
        self.route_with_summaries.assert_not_called()

    @patch("src.app.document_names", return_value=[])
    @patch("src.app.knowledge_base")
    @patch("src.app.answer", return_value=("Supplements.", []))
    def test_uncertain_questions_ask_the_model_with_summaries(self, answer, kb, _):
        summaries = [{"file": "n.pdf", "title": "Nutraceuticals", "summary": "Food-derived health products."}]
        kb.return_value.retrieve.return_value = [{"score": 0.56}]
        kb.return_value.summaries.return_value = summaries
        self.route_with_summaries.return_value = True
        response = self.client.post("/api/chat", json={"messages": [
            {"role": "user", "content": "Are fish oils regulated as food?"}]})
        self.assertEqual(response.json["mode"], "documents")
        self.route_with_summaries.assert_called_once_with("Are fish oils regulated as food?", summaries, "qwen3.5:9b")

    @patch("src.app.document_names", return_value=["Neutraceuticals.pdf"])
    @patch("src.app.knowledge_base")
    @patch("src.app.answer", return_value=("A nutrition platform.", []))
    def test_follow_ups_after_a_file_list_use_the_listed_files(self, answer, kb, _):
        kb.return_value.retrieve.return_value = [{"score": 0.3}]
        messages = [{"role": "user", "content": "What documents do I have?"},
                    {"role": "assistant", "content": "I can use these uploaded documents:\n- Neutraceuticals.pdf",
                     "mode": "library"},
                    {"role": "user", "content": "And whats inside of it?"}]
        response = self.client.post("/api/chat", json={"messages": messages})
        self.assertEqual(response.json["mode"], "documents")
        self.assertIn("Neutraceuticals.pdf", answer.call_args.args[0])
        self.assertTrue(answer.call_args.args[0].endswith("And whats inside of it?"))
        self.route_with_summaries.assert_not_called()

    @patch("src.app.document_names", return_value=["Neutraceuticals.pdf"])
    @patch("src.app.knowledge_base")
    @patch("src.app.general_answer", return_value="Sure.")
    def test_follow_ups_after_general_answers_get_no_document_context(self, general, kb, _):
        kb.return_value.retrieve.return_value = [{"score": 0.3}]
        kb.return_value.summaries.return_value = []
        messages = [{"role": "user", "content": "Neutraceuticals.pdf is a great name"},
                    {"role": "assistant", "content": "Thanks.", "mode": "general"},
                    {"role": "user", "content": "Tell me a joke about it"}]
        self.assertEqual(self.client.post("/api/chat", json={"messages": messages}).json["mode"], "general")
        kb.return_value.retrieve.assert_called_once_with("Tell me a joke about it")

    @patch("src.app.document_names", return_value=[])
    @patch("src.app.knowledge_base")
    @patch("src.app.general_answer", return_value="Hi.")
    def test_without_summaries_uncertain_questions_stay_general(self, general, kb, _):
        kb.return_value.retrieve.return_value = [{"score": 0.4}]
        kb.return_value.summaries.return_value = []
        response = self.client.post("/api/chat", json={"messages": self.messages})
        self.assertEqual(response.json["mode"], "general")
        self.route_with_summaries.assert_not_called()

    @patch("src.app.document_names", return_value=[])
    @patch("src.app.knowledge_base")
    def test_malformed_routing_decision_is_an_error(self, kb, _):
        kb.return_value.retrieve.return_value = [{"score": 0.4}]
        kb.return_value.summaries.return_value = [{"file": "a", "title": "b", "summary": "c"}]
        self.route_with_summaries.side_effect = ValueError("bad")
        self.assertEqual(self.client.post("/api/chat", json={"messages": self.messages}).status_code, 502)

    @patch("src.app.knowledge_base")
    @patch("src.app.general_answer", return_value="Paris.")
    def test_empty_library_gets_a_general_answer(self, general, kb):
        kb.return_value.retrieve.return_value = []
        response = self.client.post("/api/chat", json={"messages": self.messages})
        self.assertEqual(response.json["mode"], "general")
        general.assert_called_once()

    @patch("src.app.knowledge_base")
    @patch("src.app.general_answer", side_effect=ValueError("bad"))
    def test_malformed_general_answer_is_an_error(self, general, kb):
        kb.return_value.retrieve.return_value = []
        self.assertEqual(self.client.post("/api/chat", json={"messages": self.messages}).status_code, 502)

    @patch("src.app.knowledge_base")
    def test_invalid_input_never_retrieves(self, kb):
        for payload in (None, {}, {"messages": []}, {"messages": [None]},
                        {"messages": [{"role": "system", "content": "Hi"}]},
                        {"messages": [{"role": "user", "content": " "}]},
                        {"messages": [{"role": "assistant", "content": "Hi"}]}):
            self.assertEqual(self.client.post("/api/chat", json=payload).status_code, 400)
        kb.assert_not_called()

    @patch("src.app.knowledge_base")
    def test_unindexed_documents_and_upstream_failures_are_errors(self, kb):
        for failure, code in ((DocumentError("Index documents first"), 409),
                              (TimeoutError(), 504), (ValueError(), 502)):
            kb.return_value.retrieve.side_effect = failure
            self.assertEqual(self.client.post("/api/chat", json={"messages": self.messages}).status_code, code)

    @patch("src.app.knowledge_base")
    @patch("src.app.upload_folder")
    def test_library_question_lists_files_without_retrieval(self, folder, kb):
        document = MagicMock(is_file=lambda: True, is_symlink=lambda: False, suffix=".pdf")
        document.name = "abc--notes.pdf"
        folder.return_value.iterdir.return_value = [document]
        response = self.client.post("/api/chat", json={"messages": [
            {"role": "user", "content": "What files do you have access to?"}]})
        self.assertEqual(response.json["mode"], "library")
        self.assertIn("notes.pdf", response.json["message"]["content"])
        kb.assert_not_called()

    def test_oversized_request(self):
        response = self.client.post("/api/chat", json={"messages": [
            {"role": "user", "content": "x" * (1024 * 1024)}]})
        self.assertEqual(response.status_code, 413)
