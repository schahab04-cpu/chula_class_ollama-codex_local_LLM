import io
from pathlib import Path
import unittest
from uuid import uuid4
from unittest.mock import patch

from src.app import app, UPLOAD_LIMIT


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
        self.indexer.start()
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


if __name__ == "__main__":
    unittest.main()
