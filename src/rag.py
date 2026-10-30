"""Persistent local indexes and hybrid passage retrieval."""
import hashlib
import json
import logging
import math
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .documents import DocumentError, SUPPORTED, extract, split_passage
from .ollama_client import embed, normalized
from .answering import answer, NOT_FOUND

logger = logging.getLogger(__name__)


class KnowledgeBase:
    def __init__(self, folder, model="nomic-embed-text:latest"):
        self.folder = Path(folder)
        self.model = model

    @contextmanager
    def connect(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.folder / "knowledge.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, fingerprint TEXT, model TEXT, chunks TEXT)")
        try:
            with db:
                yield db
        finally:
            db.close()

    def fingerprint(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def ready(self, path):
        with self.connect() as db:
            row = db.execute("SELECT fingerprint, model FROM documents WHERE id=?", (path.name,)).fetchone()
        return bool(row and row["model"] == self.model and row["fingerprint"] == self.fingerprint(path))

    def index(self, path):
        fingerprint = self.fingerprint(path)
        chunks = extract(path)
        vectors = embed([c["text"] for c in chunks], self.model)
        for chunk, vector in zip(chunks, vectors):
            chunk["vector"] = vector
        # Publish the index only after every passage has been embedded successfully.
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?)",
                       (path.name, fingerprint, self.model, json.dumps(chunks)))
        return len(chunks)

    def retrieve(self, question):
        self.folder.mkdir(parents=True, exist_ok=True)
        paths = [p for p in self.folder.iterdir() if p.is_file() and not p.is_symlink()
                 and "--" in p.name and p.suffix.lower() in SUPPORTED]
        if not paths:
            return []
        for path in paths:
            if not self.ready(path):
                raise DocumentError("Some documents are not indexed. Click Index documents in the Documents panel.")
        query = embed([question], self.model, query=True)[0]
        candidates = []
        question_terms = expanded_terms(question)
        with self.connect() as db:
            rows = {row["id"]: row for row in db.execute("SELECT * FROM documents")}
        for path in paths:
            stored = json.loads(rows[path.name]["chunks"])
            if not isinstance(stored, list) or not stored:
                raise DocumentError("The document index has no passages. Reindex your documents.")
            for chunk in stored:
                if (not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str) or
                        not chunk["text"].strip() or not isinstance(chunk.get("location"), str)):
                    raise DocumentError("The document index contains invalid passages. Reindex your documents.")
                vector = normalized(chunk.get("vector"))
                if len(vector) != len(query):
                    raise DocumentError("Embedding dimensions changed. Reindex your documents.")
                score = sum(a * b for a, b in zip(query, vector))
                candidates.append({"file_id": path.name, "name": path.name.split("--", 1)[-1],
                                   "location": chunk["location"], "text": chunk["text"], "score": score})
        # Rank rather than discard by an uncalibrated cosine cutoff. Reserve
        # space for lexical hits so exact lecture terminology survives semantic
        # distractors. Reciprocal ranks combine the two scales without treating
        # term coverage or cosine similarity as a confidence probability.
        semantic = sorted(range(len(candidates)), key=lambda i: candidates[i]["score"], reverse=True)
        document_terms = [terms(c["text"]) for c in candidates]
        document_frequency = {term: sum(term in words for words in document_terms)
                              for term in question_terms}
        lexical_scores = [sum(math.log1p(len(candidates) / (1 + document_frequency[term]))
                              for term in question_terms & words)
                          for words in document_terms]
        lexical = sorted((i for i in range(len(candidates)) if lexical_scores[i]),
                         key=lambda i: (lexical_scores[i], candidates[i]["score"]), reverse=True)
        fused = {}
        for ranking in (semantic[:12], lexical[:12]):
            for rank, i in enumerate(ranking, 1):
                fused[i] = fused.get(i, 0) + 1 / (60 + rank)
        pool = set(semantic[:4] + lexical[:4])
        for i in sorted(fused, key=fused.get, reverse=True):
            if len(pool) >= 8:
                break
            pool.add(i)
        selected = [candidates[i] for i in sorted(pool, key=lambda i: fused[i], reverse=True)]
        logger.info("retrieval: scanned=%d selected=%d best_cosine=%.3f lexical_hits=%d",
                    len(candidates), len(selected), candidates[semantic[0]]["score"] if semantic else 0,
                    len(lexical))
        return selected


STOP_WORDS = set("a an the is are was were be been being do does did can could would should will shall may might must what which who whom whose when where why how much many about of for to in on at by from with and or as it its this that these those i me my we our you your please tell give show explain describe find according document documents file files uploaded information answer question der die das den dem des ein eine einer eines einem einen ist sind war waren wird werden wurde wurden hat haben hatte hatten was wer wann wo wie warum welche welcher welches welchen welchem von zu im in am an auf mit fuer und oder bitte mir mich mein meine uns unser ihr ihre sie es daten dokument dokumente datei dateien hochgeladen ueber".split())


def terms(text):
    result = set()
    for word in re.findall(r"[^\W_]+", text.casefold()):
        if word in STOP_WORDS or len(word) < 2:
            continue
        for suffix in ("ing", "ers", "er", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[:-len(suffix)]
                break
        if len(word) > 4 and word.endswith("e"):
            word = word[:-1]
        result.add(word)
    return result


def expanded_terms(text):
    result = terms(text)
    expansions = {
        "ip": {"intellectual", "property", "invention", "copyright", "patent"},
        "right": {"owner", "ownership", "own", "assign", "assignment", "transfer"},
        "assign": {"owner", "ownership", "own", "transfer", "invention", "inventor"},
        "assignment": {"owner", "ownership", "own", "transfer", "invention", "inventor"},
    }
    for term in tuple(result):
        result.update(expansions.get(term, ()))
    return result
