import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from src import quiz
from src.app import app
from src.rag import KnowledgeBase

PASSAGE = {"file_id": "a--plan.pdf", "name": "plan.pdf", "location": "Page 1",
           "text": "The platform serves students on a limited budget. Busy mothers plan family meals. "
                   "Older adults need support with chewing and mobility."}


TOPICS = ["Which group has a limited budget?", "Who plans family meals?",
          "What do older adults need support with?"]
ANSWERS = ["Students", "Busy mothers", "Chewing and mobility"]


def reply(data):
    return {"message": {"content": json.dumps(data)}}


def written(question="Which group has a limited budget?", answer="Students",
            wrong=("Busy mothers", "Older adults", "Teachers"), explanation="Students are on a limited budget."):
    return reply({"question": question, "answer": answer, "wrong_answers": list(wrong), "explanation": explanation})


def checked(question_data, chosen_text):
    """The self-check reply naming the option with this text."""
    return reply({"correct_options": [question_data["options"].index(chosen_text) + 1]})


class RequestParsingTests(unittest.TestCase):
    def test_requests_topics_and_counts(self):
        cases = {
            "Quiz me on neutraceuticals": ("neutraceuticals", 5),
            "Can you create a 7 question quiz from my documents?": ("", 7),
            "Create a quick ten question multiple choice quiz on sweetness": ("sweetness", 10),
            "Make me 3 practice questions about older adults": ("older adults", 3),
            "Hey Yapperton, quiz me": ("", 5),
            "Give me a 50 question quiz": ("", quiz.MAX_QUESTIONS),
        }
        for request, (topic, count) in cases.items():
            self.assertTrue(quiz.is_quiz_request(request), request)
            self.assertEqual((quiz.quiz_topic(request), quiz.question_count(request)), (topic, count), request)

    def test_questions_about_quizzes_are_not_requests(self):
        for question in ("What is a quiz?", "When is the quiz due?", "What does the test say about sugar?"):
            self.assertFalse(quiz.is_quiz_request(question), question)


class ValidationTests(unittest.TestCase):
    def item(self, **changes):
        data = {"question": "Which group has a limited budget?", "answer": "Students",
                "wrong_answers": ["Busy mothers", "Older adults", "Teachers"],
                "explanation": "Students are on a limited budget."}
        data.update(changes)
        return data

    def test_valid_questions_are_shuffled_with_the_answer_tracked_and_source_resolved(self):
        result = quiz._valid_question(self.item(), PASSAGE)
        self.assertEqual(result["options"][result["answer"]], "Students")
        self.assertEqual(sorted(result["options"]), ["Busy mothers", "Older adults", "Students", "Teachers"])
        self.assertEqual(result["source"]["quote"], PASSAGE["text"])

    def test_untrustworthy_questions_are_dropped(self):
        for changes in ({"question": "Which challenge does the focus statement address?"},
                        {"question": "Which group needs students support?", "answer": "Students support"},
                        {"answer": "Students who are on a very limited budget and rely on canteens daily"},
                        {"wrong_answers": ["All of the above", "Older adults", "Teachers"]},
                        {"question": "Which group is NOT served?"},
                        {"wrong_answers": ["students", "Older adults", "Teachers"]},
                        {"wrong_answers": ["Busy mothers", "Older adults"]},
                        {"answer": " "},
                        {"answer": "Students under 25", "explanation": "Students under 25 qualify."}):
            self.assertIsNone(quiz._valid_question(self.item(**changes), PASSAGE), changes)


class MakeQuizTests(unittest.TestCase):
    def test_keeps_questions_the_model_answers_back_and_drops_the_rest(self):
        calls = []

        def ollama(_endpoint, payload):
            calls.append(payload)
            if "key_idea" in payload["messages"][1]["content"]:
                number = sum("key_idea" in c["messages"][1]["content"] for c in calls)
                tag = "xyz"[number - 1]
                return written(question=TOPICS[number - 1], answer=ANSWERS[number - 1],
                               wrong=(f"Wrong {tag} one", f"Wrong {tag} two", f"Wrong {tag} three"),
                               explanation="Because.")
            shown = json.loads(payload["messages"][1]["content"])["options"]
            right = next(i for i, text in shown.items() if not text.startswith("Wrong"))
            # The check fails the second question: it also accepts a wrong option.
            extra = ["1" if right != "1" else "2"] if TOPICS[1] in payload["messages"][1]["content"] else []
            return reply({"correct_options": [int(right), *map(int, extra)]})

        with patch("src.quiz.ollama", side_effect=ollama):
            result = quiz.make_quiz("", [PASSAGE], "m", count=2, title="Plan")
        self.assertEqual([q["question"] for q in result["questions"]], [TOPICS[0], TOPICS[2]])
        self.assertEqual(result["title"], "Plan")
        first = json.loads(calls[0]["messages"][1]["content"])
        self.assertEqual(first["key_idea"], "The platform serves students on a limited budget.")
        # Rejected attempts are still listed as asked, so the model moves on.
        self.assertIn(TOPICS[1], json.loads(calls[4]["messages"][1]["content"])["already_asked"])

    def test_reworded_repeats_are_rejected(self):
        self.assertTrue(quiz._similar("Which three groups does the platform serve?",
                                      "Which groups does the platform serve, all three?"))
        self.assertFalse(quiz._similar("Which group has a limited budget?", "What do older adults need?"))

    @patch("src.quiz.ollama", return_value={"message": {"content": "not json"}})
    def test_no_usable_questions_is_an_operational_error(self, _):
        with self.assertRaises(ValueError):
            quiz.make_quiz("", [PASSAGE], "m", count=1)


class PassageSamplingTests(unittest.TestCase):
    @patch("src.rag.embed", side_effect=lambda texts, *_a, **_k: [[1.0, 0.0]] * len(texts))
    def test_whole_document_quizzes_sample_from_start_to_end(self, _):
        folder = Path(__file__).resolve().parent / ("rag-" + uuid4().hex)
        folder.mkdir()
        self.addCleanup(shutil.rmtree, folder)
        path = folder / "abc--long.txt"
        path.write_text("\n\n".join(f"Paragraph number {i} has its own fact." for i in range(20)), encoding="utf-8")
        kb = KnowledgeBase(folder)
        kb.index(path)
        sample = kb.passages(limit=4)
        self.assertEqual(len(sample), 4)
        self.assertIn("number 0 ", sample[0]["text"])
        self.assertIn("number 19 ", sample[-1]["text"])
        self.assertEqual(kb.passages(names=["other.pdf"]), [])


class QuizRouteTests(unittest.TestCase):
    QUIZ = {"title": "Plan", "questions": [{"question": "Q?", "options": ["a", "b", "c", "d"], "answer": 0,
                                            "explanation": "E.", "source": None}]}

    def setUp(self):
        self.client = app.test_client()

    @patch("src.app.make_quiz")
    @patch("src.app.knowledge_base")
    @patch("src.app.document_names", return_value=["plan.pdf"])
    def test_chat_returns_a_quiz_from_the_whole_library(self, _, kb, make_quiz):
        make_quiz.return_value = self.QUIZ
        kb.return_value.passages.return_value = [PASSAGE]
        data = self.client.post("/api/chat", json={"messages": [{"role": "user", "content": "Quiz me"}]}).get_json()
        self.assertEqual((data["mode"], data["quiz"]), ("quiz", self.QUIZ))
        self.assertIn("1-question quiz on Plan", data["message"]["content"])
        kb.return_value.passages.assert_called_once_with(names=None, limit=8)
        self.assertEqual(make_quiz.call_args.kwargs["title"], "plan")

    @patch("src.app.route_with_summaries", return_value=False)
    @patch("src.app.make_quiz")
    @patch("src.app.knowledge_base")
    @patch("src.app.document_names", return_value=["plan.pdf"])
    def test_topics_the_documents_do_not_cover_get_no_quiz(self, _, kb, make_quiz, __):
        kb.return_value.retrieve.return_value = [dict(PASSAGE, score=0.2)]
        kb.return_value.summaries.return_value = [{"file": "plan.pdf", "title": "Plan", "summary": "Meals."}]
        data = self.client.post("/api/chat", json={"messages": [
            {"role": "user", "content": "Quiz me on medieval castles"}]}).get_json()
        self.assertIsNone(data["quiz"])
        self.assertIn("don't seem to cover medieval castles", data["message"]["content"])
        make_quiz.assert_not_called()

    @patch("src.app.document_names", return_value=[])
    def test_an_empty_library_asks_for_an_upload(self, _):
        data = self.client.post("/api/chat", json={"messages": [{"role": "user", "content": "Quiz me"}]}).get_json()
        self.assertIn("Upload a document first", data["message"]["content"])

    @patch("src.app.make_quiz")
    @patch("src.app.knowledge_base")
    @patch("src.app.document_names", return_value=["plan.pdf"])
    @patch("src.speech.synthesize", return_value=b"RIFF")
    def test_voice_says_it_is_working_then_shows_and_announces_the_quiz(self, _, __, kb, make_quiz):
        make_quiz.return_value = self.QUIZ
        kb.return_value.passages.return_value = [PASSAGE]
        response = self.client.post("/api/voice/reply", json={"messages": [{"role": "user", "content": "Quiz me"}]})
        events = [json.loads(line) for line in response.get_data(as_text=True).splitlines()]
        self.assertEqual([e["type"] for e in events], ["sentence", "quiz", "sentence", "done"])
        self.assertIn("writing your quiz", events[0]["text"])
        self.assertEqual(events[1]["quiz"], self.QUIZ)
        self.assertEqual(events[-1], {"type": "done", "mode": "quiz"})


if __name__ == "__main__":
    unittest.main()
