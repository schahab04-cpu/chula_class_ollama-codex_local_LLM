import unittest
from unittest.mock import patch

from src import web_search
from src.answering import web_answer
from src.app import app

RESULTS = [{"title": "France", "url": "https://en.wikipedia.org/wiki/France", "text": "France began in 843."}]


def conversation(*texts):
    return [{"role": "user" if index % 2 == 0 else "assistant", "content": text}
            for index, text in enumerate(texts)]


class TriggerTests(unittest.TestCase):
    def test_doubts_are_challenges(self):
        for text in ("Is that right?", "that's wrong", "Are you sure? I read otherwise.",
                     "That is not correct.", "check online", "That's wrong, it was 843"):
            self.assertTrue(web_search.is_challenge(text), text)

    def test_ordinary_questions_are_not_challenges(self):
        for text in ("Is that the capital?", "check the slides for week 3", "What went wrong in 1940?"):
            self.assertFalse(web_search.is_challenge(text), text)

    def test_challenge_looks_up_the_earlier_question(self):
        messages = conversation("What year was France founded?", "51 BC", "Is that right?", "Yes.", "Are you sure?")
        self.assertEqual(web_search.search_query(messages), "What year was France founded?")

    def test_repeated_question_is_looked_up(self):
        messages = conversation("What year was France founded?", "51 BC", "Tell me what year France was founded.")
        self.assertEqual(web_search.search_query(messages), "Tell me what year France was founded.")

    def test_new_questions_and_lone_challenges_are_not_looked_up(self):
        self.assertIsNone(web_search.search_query(conversation("How are you?", "Fine.", "What is 5 times 5?")))
        self.assertIsNone(web_search.search_query(conversation("Is that right?")))

    def test_wikipedia_gets_keywords(self):
        self.assertEqual(web_search.keywords("What year was France founded?"), "year France founded")


class SearchTests(unittest.TestCase):
    @patch("src.web_search.duckduckgo")
    @patch("src.web_search.wikipedia", return_value=RESULTS)
    def test_wikipedia_comes_first(self, _, duckduckgo):
        self.assertEqual(web_search.search("q"), RESULTS)
        duckduckgo.assert_not_called()

    @patch("src.web_search.duckduckgo", return_value=RESULTS)
    def test_duckduckgo_is_the_fallback(self, _):
        for failure in ({"return_value": []}, {"side_effect": OSError("offline")}):
            with patch("src.web_search.wikipedia", **failure):
                self.assertEqual(web_search.search("q"), RESULTS)

    @patch("src.web_search.duckduckgo", side_effect=OSError("offline"))
    @patch("src.web_search.wikipedia", side_effect=OSError("offline"))
    def test_both_failing_is_an_operational_error(self, _, __):
        with self.assertRaises(web_search.SearchError):
            web_search.search("q")

    @patch("src.web_search.duckduckgo", return_value=[])
    @patch("src.web_search.wikipedia", return_value=[])
    def test_nothing_found_is_empty(self, _, __):
        self.assertEqual(web_search.search("q"), [])

    @patch("src.web_search._get_json")
    def test_off_topic_wikipedia_titles_are_dropped(self, get_json):
        get_json.return_value = {"query": {"pages": [
            {"index": 1, "title": "Toy Story 5", "fullurl": "https://en.wikipedia.org/wiki/Toy_Story_5", "extract": "A film."},
            {"index": 2, "title": "France", "fullurl": "https://en.wikipedia.org/wiki/France", "extract": "A country."}]}}
        self.assertEqual([page["title"] for page in web_search.wikipedia("When was France 5 founded?")], ["France"])


class WebAnswerTests(unittest.TestCase):
    @patch("src.answering.ollama", return_value={"message": {"content": "I was wrong: 843."}})
    def test_answer_cites_result_urls(self, ollama):
        text, sources = web_answer(conversation("When?", "51 BC", "Is that right?"), "When?", RESULTS, "qwen")
        self.assertEqual(text, "I was wrong: 843.")
        self.assertEqual(sources, [{"url": RESULTS[0]["url"], "name": "France", "location": "Wikipedia",
                                    "quote": "France began in 843."}])
        self.assertIn("51 BC", ollama.call_args[0][1]["messages"][1]["content"])

    @patch("src.answering.ollama")
    def test_no_results_skips_the_model(self, ollama):
        text, sources = web_answer(conversation("When?"), "When?", [], "qwen")
        self.assertEqual(sources, [])
        ollama.assert_not_called()

    @patch("src.answering.ollama", return_value={"message": {"content": " "}})
    def test_empty_model_output_is_an_error(self, _):
        with self.assertRaises(ValueError):
            web_answer(conversation("When?"), "When?", RESULTS, "qwen")


@patch("src.app.knowledge_base")
class ChatRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.messages = conversation("What year was France founded?", "51 BC", "Is that right?")

    @patch("src.app.web_answer", return_value=("It began in 843.", []))
    @patch("src.web_search.search", return_value=RESULTS)
    def test_challenge_searches_online(self, search, _, kb):
        kb.return_value.retrieve.return_value = [{"score": 0.3}]
        response = self.client.post("/api/chat", json={"messages": self.messages})
        self.assertEqual(response.json["mode"], "web")
        search.assert_called_once_with("What year was France founded?")

    @patch("src.app.general_answer", return_value="Yes.")
    @patch("src.web_search.search")
    def test_document_questions_stay_with_documents(self, search, _, kb):
        kb.return_value.retrieve.return_value = [{"score": 0.9}]
        with patch("src.app.answer", return_value=("From the slides.", [])):
            response = self.client.post("/api/chat", json={"messages": self.messages})
        search.assert_not_called()
        self.assertNotEqual(response.json["mode"], "web")

    @patch("src.web_search.search", side_effect=web_search.SearchError("Online search failed."))
    def test_search_failure_is_reported(self, _, kb):
        kb.return_value.retrieve.return_value = []
        response = self.client.post("/api/chat", json={"messages": self.messages})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error"], "Online search failed.")


if __name__ == "__main__":
    unittest.main()
