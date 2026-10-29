import unittest
from unittest.mock import patch, MagicMock
from src.app import app, main
from src.rag import DocumentError, NOT_FOUND


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.messages = [{"role": "user", "content": "What is the launch date?"}]

    @patch("src.app.app.run")
    def test_startup_uses_only_localhost_port_5000(self, run):
        with patch("sys.argv", ["app.py"]):
            main()
        run.assert_called_once_with(host="127.0.0.1", port=5000, debug=False)

    def test_page_and_assets(self):
        for path in ("/", "/static/chat.js", "/static/files.js", "/static/views.js", "/static/style.css"):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="files-view"', html)
        self.assertIn('aria-labelledby="documents-title" hidden', html)

    @patch("src.app.knowledge_base")
    @patch("src.app.answer")
    def test_answers_are_retrieved_from_latest_user_question(self, answer, kb):
        kb.return_value.retrieve.return_value = []
        answer.return_value = (NOT_FOUND, [])
        response = self.client.post("/api/chat", json={"messages": self.messages})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["message"]["content"], NOT_FOUND)
        kb.return_value.retrieve.assert_called_once_with("What is the launch date?")

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

    def test_oversized_request(self):
        response = self.client.post("/api/chat", json={"messages": [
            {"role": "user", "content": "x" * (1024 * 1024)}]})
        self.assertEqual(response.status_code, 413)
