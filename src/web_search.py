"""Online fact checks: Wikipedia first, DuckDuckGo when Wikipedia finds nothing.

This is the only module that sends text off this machine, and only the user's question.
"""
import json
import logging
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
# Wikimedia asks automated clients to identify themselves.
USER_AGENT = "LocalOllamaChat/1.0 (local study app)"
TIMEOUT = 10
MAX_RESULTS = 3
MAX_CHARS = 3000
logger = logging.getLogger(__name__)

# Replies that doubt the last answer or ask to look it up, matched against the whole message.
_CHALLENGE = re.compile(
    r"(?:(?:are|r)\s+(?:you|u)\s+sure|(?:is|was)\s+(?:that|this|it)\s+(?:really\s+)?(?:right|correct|true|accurate)"
    r"|(?:that(?:'s|\s+is|\s+was)?|this\s+is|it(?:'s|\s+is))\s+(?:not\s+(?:right|correct|true)|wrong|incorrect|false)"
    r"|(?:you(?:'re|\s+are)\s+)?wrong|(?:no,?\s+)?(?:that|this)\s+(?:can't|cannot)\s+be\s+right"
    r"|(?:please\s+)?(?:check|verify|look\s+(?:it|that)\s+up|search)(?:\s+(?:it|that|this))?"
    r"(?:\s+(?:online|on\s+the\s+(?:web|internet)|on\s+wikipedia))?)"
    r"(?:[\s?.!]*|[,.;:!?]\s.*)", re.I | re.S)
_STOP_WORDS = set(
    "a an and are as at be been but by can could did do does for from had has have how i in is it its "
    "calculate me of on or please tell that the this to was were what when where which who why will with "
    "would you your".split())


class SearchError(RuntimeError):
    """Neither search service answered; an operational error, not evidence absence."""


def _words(text):
    return {word for word in re.findall(r"[a-z0-9]+", text.casefold()) if word not in _STOP_WORDS}


def _stems(text):
    # "founded" and "founding", "australia" and "australian" share a stem.
    # Numbers alone do not make a title on topic ("5 times 5" is not "Toy Story 5").
    return {word[:5] for word in _words(text) if not word.isdigit()}


def keywords(query):
    """Wikipedia's search handles keywords far better than whole sentences."""
    return " ".join(word for word in re.findall(r"[^\W_]+", query) if word.casefold() not in _STOP_WORDS)


def is_challenge(question):
    return _CHALLENGE.fullmatch(question.strip()) is not None


def search_query(messages):
    """Return the question to look up, or None when the message is not a fact check.

    A challenge ("is that right?") looks up the latest earlier question. Asking
    nearly the same question again looks up that question.
    """
    question = messages[-1]["content"].strip()
    earlier = [message["content"].strip() for message in messages[:-1] if message["role"] == "user"]
    if is_challenge(question):
        return next((text for text in reversed(earlier) if not is_challenge(text)), None)
    words = _words(question)
    for text in earlier:
        previous = _words(text)
        if words and previous and len(words & previous) / len(words | previous) >= 0.6:
            return question
    return None


def _get_json(url):
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=TIMEOUT) as response:
        return json.load(response)


def wikipedia(query):
    params = {"action": "query", "format": "json", "formatversion": 2, "generator": "search",
              "gsrsearch": query, "gsrlimit": MAX_RESULTS, "prop": "extracts|info",
              "exintro": 1, "explaintext": 1, "inprop": "url"}
    params["gsrsearch"] = keywords(query) or query
    pages = _get_json(f"{WIKIPEDIA_API}?{urlencode(params)}").get("query", {}).get("pages", [])
    pages = sorted(pages, key=lambda page: page.get("index", 0))
    # Full-text search always returns something; keep only articles whose title is on topic.
    wanted = _stems(query)
    return [{"title": page["title"], "url": page["fullurl"], "text": page["extract"].strip()[:MAX_CHARS]}
            for page in pages if page.get("extract", "").strip() and page.get("fullurl")
            and _stems(page["title"]) & wanted]


def duckduckgo(query):
    from ddgs import DDGS

    results = DDGS(timeout=TIMEOUT).text(query, max_results=MAX_RESULTS + 2)
    return [{"title": item["title"], "url": item["href"], "text": item["body"].strip()[:MAX_CHARS]}
            for item in results if item.get("body", "").strip() and item.get("href")]


def search(query):
    """Return results as {title, url, text}; empty when both services found nothing."""
    failures = 0
    for name, service in (("Wikipedia", wikipedia), ("DuckDuckGo", duckduckgo)):
        try:
            results = service(query)
        except Exception:
            logger.warning("%s search failed", name, exc_info=True)
            failures += 1
            continue
        if results:
            logger.info("web search: %d results from %s", len(results), name)
            return results
    if failures == 2:
        raise SearchError("Online search failed. Check the internet connection.")
    return []
