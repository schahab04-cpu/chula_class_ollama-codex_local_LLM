import re
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.app import app, main
from src.rag import DocumentError, NOT_FOUND


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.messages = [{"role": "user", "content": "What is the launch date?"}]

    @patch("src.app.app.run")
    def test_startup_uses_only_localhost_port_5050(self, run):
        with patch("sys.argv", ["app.py"]):
            main()
        run.assert_called_once_with(host="127.0.0.1", port=5050, debug=False)

    def test_page_and_assets(self):
        for path in ("/", "/static/chat.js", "/static/files.js", "/static/views.js", "/static/wisp.js", "/static/voice.js", "/static/style.css"):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="files-view"', html)
        self.assertIn('id="dropzone"', html)
        self.assertIn('id="preview-dialog"', html)

    def test_page_scripts_share_no_top_level_names(self):
        # Classic scripts share one global scope: a repeated let/const stops the later script loading.
        static = Path(__file__).resolve().parent.parent / "src" / "static"
        declared = [set(re.findall(r"^(?:let|const|(?:async )?function) +(\w+)",
                                   (static / name).read_text(encoding="utf-8"), re.M))
                    for name in ("chat.js", "files.js", "voice.js", "wisp.js")]
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
        general.assert_called_once_with(history, "qwen3:1.7b")
        answer.assert_not_called()

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
