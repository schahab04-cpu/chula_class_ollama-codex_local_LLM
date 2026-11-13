import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from src import app as app_module
from src.app import app, refresh_index
from src.rag import DocumentError, KnowledgeBase


class AutomaticIndexingTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(__file__).resolve().parent / ("files-" + uuid4().hex)
        self.folder.mkdir()
        self.addCleanup(shutil.rmtree, self.folder)
        previous = app.config["UPLOAD_FOLDER"]
        app.config["UPLOAD_FOLDER"] = self.folder
        self.addCleanup(app.config.__setitem__, "UPLOAD_FOLDER", previous)
        app_module._index_failures.clear()
        self.addCleanup(app_module._index_failures.clear)
        self.client = app.test_client()

    @patch("src.rag.summarize_document", return_value=("T", "S."))
    @patch("src.rag.embed", side_effect=lambda texts, *_a, **_k: [[1.0, 0.0]] * len(texts))
    def test_new_and_changed_files_are_indexed_without_a_button(self, embed, _):
        path = self.folder / "abc--notes.txt"
        path.write_text("The launch date is 15 June 2027.", encoding="utf-8")
        refresh_index()
        self.assertTrue(KnowledgeBase(self.folder).ready(path))
        calls = embed.call_count
        refresh_index()
        self.assertEqual(embed.call_count, calls)
        path.write_text("The launch moved to 1 July 2027.", encoding="utf-8")
        refresh_index()
        self.assertTrue(KnowledgeBase(self.folder).ready(path))

    @patch("src.rag.embed", side_effect=lambda texts, *_a, **_k: [[1.0, 0.0]] * len(texts))
    def test_unreadable_files_are_reported_and_not_retried_until_they_change(self, _):
        path = self.folder / "abc--broken.txt"
        path.write_bytes(b"\xff\xfe\x00binary")
        with patch("src.rag.extract", side_effect=DocumentError("This file is not UTF-8 text.")) as extract:
            refresh_index()
            refresh_index()
            self.assertEqual(extract.call_count, 1)
            listed = self.client.get("/api/files").get_json()["files"][0]
            self.assertEqual((listed["indexed"], listed["error"]), (False, "This file is not UTF-8 text."))
            path.write_bytes(b"\xff\xfe\x00other")
            refresh_index()
            self.assertEqual(extract.call_count, 2)


class BusyAndUploadTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_questions_wait_while_documents_are_read(self):
        self.assertEqual(self.client.get("/api/documents/status").get_json(), {"busy": False, "detail": ""})
        with app_module.processing("Reading notes.pdf"):
            self.assertEqual(self.client.get("/api/documents/status").get_json(),
                             {"busy": True, "detail": "Reading notes.pdf"})
            for url in ("/api/chat", "/api/voice/reply"):
                response = self.client.post(url, json={"messages": [{"role": "user", "content": "Hi"}]})
                self.assertEqual(response.status_code, 409, url)
                self.assertTrue(response.get_json()["busy"])
        self.assertFalse(self.client.get("/api/documents/status").get_json()["busy"])

    @patch("src.app.knowledge_base")
    def test_upload_requests_open_the_upload_box_in_chat(self, kb):
        data = self.client.post("/api/chat", json={"messages": [
            {"role": "user", "content": "I want to upload a document"}]}).get_json()
        self.assertEqual(data["mode"], "upload")
        kb.assert_not_called()

    @patch("src.speech.synthesize", return_value=b"RIFF")
    def test_upload_requests_open_the_upload_box_in_voice(self, _):
        response = self.client.post("/api/voice/reply", json={"messages": [
            {"role": "user", "content": "Can I upload my notes?"}]})
        events = [__import__("json").loads(line) for line in response.get_data(as_text=True).splitlines()]
        self.assertEqual([e["type"] for e in events], ["upload", "sentence", "done"])
        self.assertEqual(events[-1]["mode"], "upload")

    def test_upload_intent_is_told_apart_from_questions_about_uploads(self):
        from src.answering import is_upload_request
        for text in ("I want to upload a document", "Let me add a PDF", "Can I share my slides with you?", "upload"):
            self.assertTrue(is_upload_request(text), text)
        for text in ("What does the uploaded document say?", "What documents did I add?",
                     "Which files are uploaded?", "How do I add a column in Excel?"):
            self.assertFalse(is_upload_request(text), text)


if __name__ == "__main__":
    unittest.main()
