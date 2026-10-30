import hashlib
import io
from pathlib import Path
import unittest
from uuid import uuid4
from unittest.mock import patch

from src.app import app, UPLOAD_LIMIT
from src.rag import DocumentError


class FileManagerTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(__file__).resolve().parent / f"files-{uuid4().hex}"
        self.folder.mkdir()
        self.addCleanup(self.clean_files)
        previous = app.config["UPLOAD_FOLDER"]
        self.addCleanup(app.config.update, UPLOAD_FOLDER=previous)
        app.config["UPLOAD_FOLDER"] = self.folder
        self.client = app.test_client()
        self.indexer = patch("src.app.KnowledgeBase.index", return_value=1)
        self.index = self.indexer.start()
        self.addCleanup(self.indexer.stop)

    def clean_files(self):
        for path in self.folder.iterdir():
            path.unlink()
        self.folder.rmdir()

    def upload(self, name="notes.txt", content=b"Local notes"):
        return self.client.post("/api/files", data={
            "file": (io.BytesIO(content), name)
        })

    def test_upload_list_download_and_persistence(self):
        self.assertEqual(self.client.get("/api/files").json, {"files": []})
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        saved = response.json["file"]
        self.assertEqual(saved["name"], "notes.txt")
        self.assertEqual(saved["size"], 11)
        # A different client sees the same files; history is not needed.
        self.assertEqual(app.test_client().get("/api/files").json["files"], [saved])
        with self.client.get(f"/api/files/{saved['id']}") as download:
            self.assertEqual(download.data, b"Local notes")
            self.assertIn("attachment", download.headers["Content-Disposition"])

    def test_duplicate_names_preserve_both_files(self):
        first = self.upload(content=b"first").json["file"]
        second = self.upload(content=b"second").json["file"]
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.client.get("/api/files").json["files"]), 2)
        self.assertEqual((self.folder / first["id"]).read_bytes(), b"first")

    def test_filenames_are_sanitized(self):
        response = self.upload("../../<script>alert.txt")
        self.assertEqual(response.status_code, 201)
        saved = response.json["file"]
        self.assertEqual(saved["name"], "scriptalert.txt")
        self.assertTrue((self.folder / saved["id"]).is_file())

    def test_missing_invalid_and_missing_download(self):
        self.assertEqual(self.client.post("/api/files").status_code, 400)
        self.assertEqual(self.upload("...").status_code, 400)
        self.assertEqual(self.client.get("/api/files/missing--file.txt").status_code, 404)
        self.assertEqual(self.client.get("/api/files/..%5CAGENTS.md").status_code, 404)

    def test_large_upload_allowed_but_limit_enforced(self):
        self.assertEqual(self.upload(content=b"x" * (2 * 1024 * 1024)).status_code, 201)
        response = self.upload(content=b"x" * UPLOAD_LIMIT)
        self.assertEqual(response.status_code, 413)
        self.assertIn("20 MiB", response.json["error"])
        self.assertEqual(len(self.client.get("/api/files").json["files"]), 1)

    def test_pdf_preview_is_served_inline(self):
        saved = self.upload("slides.pdf", b"%PDF-1.4 test").json["file"]
        with self.client.get(f"/api/files/{saved['id']}/preview") as preview:
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview.mimetype, "application/pdf")
            self.assertNotIn("attachment", preview.headers.get("Content-Disposition", ""))
            self.assertEqual(preview.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(preview.data, b"%PDF-1.4 test")

    def test_preview_rejects_other_files(self):
        text = self.upload().json["file"]
        for file_id in (text["id"], f"{text['id']}.sha256", "missing--file.pdf", "..%5CAGENTS.md"):
            with self.subTest(file_id=file_id):
                self.assertEqual(self.client.get(f"/api/files/{file_id}/preview").status_code, 404)

    def test_same_content_upload_does_nothing(self):
        first = self.upload()
        self.assertEqual(self.index.call_count, 1)
        before = sorted(path.name for path in self.folder.iterdir())
        for name in ("notes.txt", "renamed.txt"):
            with self.subTest(name=name):
                again = self.upload(name)
                self.assertEqual(again.status_code, 200)
                self.assertTrue(again.json["duplicate"])
                self.assertEqual(again.json["file"]["id"], first.json["file"]["id"])
        self.assertEqual(self.index.call_count, 1)
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), before)

    def test_hash_is_saved_beside_the_file_and_never_listed(self):
        saved = self.upload().json["file"]
        stored = self.folder / f"{saved['id']}.sha256"
        self.assertEqual(stored.read_text(), hashlib.sha256(b"Local notes").hexdigest())
        self.assertEqual(self.client.get("/api/files").json["files"], [saved])
        self.assertEqual(self.client.get(f"/api/files/{stored.name}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/files/{stored.name}").status_code, 404)

    def test_existing_document_without_hash_is_detected(self):
        existing = self.folder / "abc--older.txt"
        existing.write_bytes(b"Local notes")
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["file"]["id"], existing.name)
        self.assertTrue((self.folder / "abc--older.txt.sha256").is_file())
        self.index.assert_not_called()

    def test_deleted_document_can_be_uploaded_again(self):
        saved = self.upload().json["file"]
        self.assertEqual(self.client.delete(f"/api/files/{saved['id']}").status_code, 204)
        self.assertEqual(list(self.folder.glob("*.sha256")), [])
        self.assertEqual(self.upload().status_code, 201)

    def test_failed_index_leaves_nothing_and_can_be_retried(self):
        self.index.side_effect = DocumentError("No readable text found.")
        self.assertEqual(self.upload().status_code, 400)
        self.assertEqual([path.name for path in self.folder.iterdir()
                          if path.name != "knowledge.sqlite3"], [])
        self.index.side_effect = None
        self.assertEqual(self.upload().status_code, 201)


if __name__ == "__main__":
    unittest.main()
