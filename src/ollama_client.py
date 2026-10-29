"""Local Ollama transport and Nomic embeddings; no external services."""
import json
import math
from urllib.request import Request, urlopen


def ollama(endpoint, payload):
    req = Request("http://localhost:11434/api/" + endpoint,
                  data=json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=120) as response:
        result = json.load(response)
    if not isinstance(result, dict) or result.get("error"):
        raise ValueError("Ollama returned an invalid response.")
    return result


def normalized(vector):
    if (not isinstance(vector, list) or not vector or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in vector)):
        raise ValueError("Invalid embedding vector from Ollama.")
    length = math.sqrt(sum(v * v for v in vector))
    if not length:
        raise ValueError("Ollama returned an empty embedding.")
    return [v / length for v in vector]


def embed(texts, model, query=False):
    prefix = "search_query: " if query else "search_document: "
    vectors = []
    for start in range(0, len(texts), 16):
        batch = texts[start:start + 16]
        result = ollama("embed", {"model": model,
            "input": [prefix + text for text in batch], "truncate": False})
        items = result.get("embeddings")
        if not isinstance(items, list) or len(items) != len(batch):
            raise ValueError("Ollama returned an unexpected embedding count.")
        vectors.extend(normalized(item) for item in items)
    if len({len(v) for v in vectors}) > 1:
        raise ValueError("Ollama returned inconsistent embedding dimensions.")
    return vectors


