import io
import json
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from src import answering, ollama_client, speech
from src.app import VOICE_LIMIT, app
from src.documents import DocumentError


def stream_of(items):
    yield from items


def wav_bytes(rate=16000, channels=1, frames=1600):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(bytes(frames * channels * 2))
    return output.getvalue()


class SentenceTests(unittest.TestCase):
    def split(self, *chunks):
        return list(speech.split_sentences(chunks))

    def test_sentences_end_across_stream_chunks(self):
        self.assertEqual(self.split("Hello th", "ere. How are", " you? Fine"),
                         ["Hello there.", "How are you?", "Fine"])

    def test_abbreviations_decimals_and_list_numbers_do_not_split(self):
        self.assertEqual(self.split("Dr. Lee paid 3.14 dollars. Next one."),
                         ["Dr. Lee paid 3.14 dollars.", "Next one."])
        self.assertEqual(self.split("Use e.g. this. 1. First item."),
                         ["Use e.g. this.", "1. First item."])

    def test_newlines_split_and_blank_text_yields_nothing(self):
        self.assertEqual(self.split("One\n\nTwo"), ["One", "Two"])
        self.assertEqual(self.split("  ", "\n"), [])

    def test_closing_the_splitter_closes_its_source(self):
        closed = []

        def source():
            try:
                yield "First. "
                yield "Second. "
            finally:
                closed.append(True)

        chunks = source()
        sentences = speech.split_sentences(chunks)
        self.assertEqual(next(sentences), "First.")
        sentences.close()
        chunks.close()
        self.assertEqual(closed, [True])


class CleanTests(unittest.TestCase):
    def test_markup_is_not_read_aloud(self):
        self.assertEqual(speech.clean_for_speech("- **Bold** and `code`"), "Bold and code")
        self.assertEqual(speech.clean_for_speech("### Title"), "Title")
        self.assertEqual(speech.clean_for_speech("2. See [the docs](http://x.io)."), "See the docs.")
        self.assertEqual(speech.clean_for_speech("Open https://x.io now"), "Open a link now")
        self.assertEqual(speech.clean_for_speech("snake_case stays"), "snake_case stays")

    def test_nothing_speakable_is_empty(self):
        self.assertEqual(speech.clean_for_speech("```\n```"), "")
        self.assertEqual(speech.clean_for_speech("***"), "")


class BackendTests(unittest.TestCase):
    def test_onnx_backend_needs_whisper_and_both_kokoro_files(self):
        with patch.object(speech, "MLX", False), \
                patch.object(speech, "WHISPER_PATH", Path("/w")), patch.object(speech, "KOKORO_PATH", Path("/k")):
            self.assertEqual(speech.model_files(), [Path("/w/model.bin"), Path("/k/kokoro-v1.0.onnx"),
                                                    Path("/k/voices-v1.0.bin")])

    @patch("src.speech._load_whisper")
    def test_onnx_backend_joins_segments(self, load):
        load.return_value.transcribe.return_value = ([MagicMock(text=" Hello"), MagicMock(text=" there.")], None)
        with patch.object(speech, "MLX", False):
            self.assertEqual(speech._recognize(bytes(3200)), "Hello there.")
        self.assertEqual(load.return_value.transcribe.call_args.kwargs["language"], "en")

    @patch("src.speech._load_kokoro")
    def test_onnx_backend_writes_wav_at_the_models_rate(self, load):
        import numpy as np

        load.return_value.create.return_value = (np.zeros(2400, dtype=np.float32), 24000)
        with patch.object(speech, "MLX", False):
            data = speech._render("Hi.")
        with wave.open(io.BytesIO(data)) as audio:
            self.assertEqual((audio.getframerate(), audio.getnframes()), (24000, 2400))


class TranscribeTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def post(self, data):
        return self.client.post("/api/voice/transcribe", data=data, content_type="audio/wav")

    @patch("src.speech.available", return_value=True)
    @patch("src.speech._recognize", return_value="Hello there.")
    def test_returns_text(self, recognize, _):
        response = self.post(wav_bytes())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"text": "Hello there."})
        recognize.assert_called_once()

    @patch("src.speech.available", return_value=True)
    def test_noise_phrases_and_empty_results_become_empty_text(self, _):
        for heard in ("Thank you.", " you ", "", "..."):
            with patch("src.speech._recognize", return_value=heard):
                self.assertEqual(self.post(wav_bytes()).get_json(), {"text": ""})

    @patch("src.speech.available", return_value=True)
    @patch("src.speech._recognize")
    def test_malformed_audio_is_rejected_before_the_model(self, recognize, _):
        for data in (b"", b"not audio", wav_bytes(rate=44100), wav_bytes(channels=2), wav_bytes(frames=0)):
            self.assertEqual(self.post(data).status_code, 400)
        recognize.assert_not_called()

    def test_oversized_audio_gets_a_clear_error(self):
        response = self.post(bytes(VOICE_LIMIT + 1))
        self.assertEqual(response.status_code, 413)
        self.assertIn("too long", response.get_json()["error"])

    @patch("src.speech.available", return_value=False)
    def test_missing_speech_models_are_operational_errors(self, _):
        response = self.post(wav_bytes())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], speech.UNAVAILABLE)

    @patch("src.speech.available", return_value=True)
    @patch("src.speech._recognize", side_effect=RuntimeError("metal failure"))
    def test_model_failures_are_operational_errors(self, _, __):
        with self.assertLogs("src.speech", level="ERROR"):
            self.assertEqual(self.post(wav_bytes()).status_code, 503)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_status_explains_when_unavailable(self):
        with patch("src.speech.available", return_value=False):
            data = self.client.get("/api/voice/status").get_json()
        self.assertEqual(data, {"available": False, "reason": speech.UNAVAILABLE})
        with patch("src.speech.available", return_value=True):
            self.assertTrue(self.client.get("/api/voice/status").get_json()["available"])

    @patch("src.app.knowledge_base")
    @patch("src.app.warm_up_voice_model")
    @patch("src.speech.warm_up")
    def test_warmup_reports_missing_ollama(self, _, warm_model, knowledge_base):
        self.assertEqual(self.client.post("/api/voice/warmup").status_code, 204)
        knowledge_base.return_value.warm_up.assert_called_once_with(answering.VOICE_KEEP_ALIVE)
        warm_model.side_effect = URLError("down")
        self.assertEqual(self.client.post("/api/voice/warmup").status_code, 503)

    @patch("src.speech.fillers", return_value=[("Hmm.", b"RIFF")])
    def test_fillers_return_base64_audio(self, _):
        data = self.client.get("/api/voice/fillers").get_json()
        self.assertEqual(data, {"fillers": [{"text": "Hmm.", "audio": "UklGRg=="}]})

    @patch("src.speech.fillers", side_effect=speech.SpeechError("Local speech processing failed."))
    def test_filler_failures_are_operational_errors(self, _):
        response = self.client.get("/api/voice/fillers")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"error": "Local speech processing failed."})

    def test_vad_assets_have_module_and_wasm_types(self):
        for name, kind in (("ort-wasm-simd-threaded.mjs", "text/javascript"),
                           ("ort-wasm-simd-threaded.wasm", "application/wasm")):
            with self.client.get(f"/static/vendor/vad/{name}") as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, kind)


class ReplyTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.messages = [{"role": "user", "content": "How are you?"}]
        # No documents: every turn routes to general chat without touching uploads or Ollama.
        for target, value in (("src.app.document_names", []), ("src.app.knowledge_base", None)):
            patcher = patch(target, return_value=value) if value is not None else patch(target)
            mocked = patcher.start()
            self.addCleanup(patcher.stop)
            if value is None:
                mocked.return_value.retrieve.return_value = []

    def events(self):
        response = self.client.post("/api/voice/reply", json={"messages": self.messages})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/x-ndjson")
        return [json.loads(line) for line in response.get_data(as_text=True).splitlines()]

    @patch("src.speech.synthesize", return_value=b"RIFF")
    @patch("src.app.voice_reply", return_value=stream_of(["Doing **well**. ", "Thanks", " for asking."]))
    def test_events_arrive_in_order_with_clean_text(self, _, synthesize):
        events = self.events()
        self.assertEqual([event["type"] for event in events], ["sentence", "sentence", "done"])
        self.assertEqual(events[0]["text"], "Doing well.")
        self.assertEqual(events[0]["audio"], "UklGRg==")
        self.assertEqual(synthesize.call_args_list[1].args, ("Thanks for asking.",))

    @patch("src.speech.synthesize", return_value=b"RIFF")
    def test_ollama_failing_mid_stream_becomes_an_error_event(self, _):
        def failing(_messages, _model):
            yield "First part. "
            raise URLError("gone")

        with patch("src.app.voice_reply", failing):
            events = self.events()
        self.assertEqual([event["type"] for event in events], ["sentence", "error"])
        self.assertIn("Ollama", events[1]["message"])

    @patch("src.speech.synthesize", side_effect=speech.SpeechError("Local speech processing failed."))
    @patch("src.app.voice_reply", return_value=stream_of(["Hello. "]))
    def test_speech_failures_become_error_events(self, _, __):
        self.assertEqual(self.events(), [{"type": "error", "message": "Local speech processing failed."}])

    @patch("src.app.voice_reply", return_value=stream_of(["***", ""]))
    def test_empty_answers_are_errors(self, _):
        self.assertEqual(self.events()[-1]["type"], "error")

    def test_invalid_history_is_rejected(self):
        for messages in ([], [{"role": "assistant", "content": "Hi"}], [{"role": "user", "content": "x" * 4001}]):
            response = self.client.post("/api/voice/reply", json={"messages": messages})
            self.assertEqual(response.status_code, 400)

    @patch("src.speech.synthesize", return_value=b"RIFF")
    def test_abandoning_the_reply_stops_generation(self, _):
        closed = []

        def endless(_messages, _model):
            try:
                while True:
                    yield "More words. "
            finally:
                closed.append(True)

        with patch("src.app.voice_reply", endless):
            response = self.client.post("/api/voice/reply", json={"messages": self.messages}, buffered=False)
            next(response.response)
            response.close()
        self.assertEqual(closed, [True])


PASSAGE = {"file_id": "a--syllabus.pdf", "name": "syllabus.pdf", "location": "Page 2", "score": 0.8,
           "text": "The final project report is due on December 5 and counts for 40 percent of the grade."}


@patch("src.speech.synthesize", return_value=b"RIFF")
@patch("src.app.document_names", return_value=["syllabus.pdf"])
@patch("src.app.knowledge_base")
class VoiceDocumentTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        # The summary router is a model call; these tests cover the code-decided routes.
        router = patch("src.app.route_with_summaries", return_value=False)
        self.route_with_summaries = router.start()
        self.addCleanup(router.stop)

    def events(self, messages):
        response = self.client.post("/api/voice/reply", json={"messages": messages})
        return [json.loads(line) for line in response.get_data(as_text=True).splitlines()]

    def ask(self, text):
        return [{"role": "user", "content": text}]

    @patch("src.app.select_evidence", side_effect=lambda question, sources, model: sources)
    def test_document_questions_stream_a_spoken_answer_with_sources(self, select, knowledge_base, *_):
        knowledge_base.return_value.retrieve.return_value = [PASSAGE]
        reply = stream_of(["The final project report is due on December 5 at noon. ", "It counts for 40 percent."])
        with patch("src.app.voice_document_reply", return_value=reply) as document_reply:
            events = self.events(self.ask("When is the final project due?"))
        self.assertEqual([event["type"] for event in events], ["sentence", "sentence", "sources", "done"])
        self.assertEqual(events[-1]["mode"], "documents")
        self.assertEqual(events[2]["sources"][0]["file_id"], "a--syllabus.pdf")
        self.assertEqual(document_reply.call_args.args[1], [PASSAGE])
        self.assertEqual(knowledge_base.return_value.retrieve.call_args.kwargs["keep_alive"],
                         answering.VOICE_KEEP_ALIVE)

    @patch("src.app.select_evidence", side_effect=lambda question, sources, model: sources)
    def test_sentences_with_unsupported_figures_are_replaced(self, _, knowledge_base, *__):
        knowledge_base.return_value.retrieve.return_value = [PASSAGE]
        reply = stream_of(["It is due on December 5 at noon. ", "Late work loses 15 percent. ", "Teams have 7 people."])
        with patch("src.app.voice_document_reply", return_value=reply):
            events = self.events(self.ask("When is the final project due?"))
        texts = [event["text"] for event in events if event["type"] == "sentence"]
        self.assertEqual(texts, ["It is due on December 5 at noon.", answering.UNCONFIRMED_FIGURE])

    @patch("src.app.select_evidence", side_effect=lambda question, sources, model: sources)
    def test_an_echoed_question_is_not_spoken(self, _, knowledge_base, *__):
        knowledge_base.return_value.retrieve.return_value = [PASSAGE]
        reply = stream_of(["When is the final project due? ", "It is due on December 5 at noon."])
        with patch("src.app.voice_document_reply", return_value=reply):
            events = self.events(self.ask("When is the final project due?"))
        self.assertEqual([event["text"] for event in events if event["type"] == "sentence"],
                         ["It is due on December 5 at noon."])

    @patch("src.app.select_evidence", return_value=[])
    def test_no_selected_evidence_says_not_found(self, _, knowledge_base, *__):
        knowledge_base.return_value.retrieve.return_value = [PASSAGE]
        events = self.events(self.ask("Who is the instructor?"))
        self.assertEqual(events[0]["text"], answering.NOT_FOUND)
        self.assertEqual(events[-1], {"type": "done", "mode": "documents"})

    def test_general_questions_skip_the_documents(self, knowledge_base, *_):
        knowledge_base.return_value.retrieve.return_value = [dict(PASSAGE, score=0.3)]
        with patch("src.app.voice_reply", return_value=stream_of(["Sure. "])), \
                patch("src.app.select_evidence") as select:
            events = self.events(self.ask("Tell me a joke"))
        select.assert_not_called()
        self.assertEqual(events[-1], {"type": "done", "mode": "general"})

    @patch("src.app.select_evidence", side_effect=lambda question, sources, model: sources)
    def test_follow_ups_after_document_answers_reuse_the_previous_question(self, select, knowledge_base, *_):
        def retrieve(question, keep_alive=None):
            return [dict(PASSAGE, score=0.8 if "report" in question else 0.3)]

        knowledge_base.return_value.retrieve.side_effect = retrieve
        messages = [{"role": "user", "content": "When is the report due?"},
                    {"role": "assistant", "content": "December 5.", "mode": "documents"},
                    {"role": "user", "content": "And how much does it count?"}]
        with patch("src.app.voice_document_reply", return_value=stream_of(["It counts for 40 percent."])):
            events = self.events(messages)
        self.assertEqual(events[-1]["mode"], "documents")
        self.assertEqual(select.call_args.args[0], "When is the report due?\nAnd how much does it count?")
        messages[1]["mode"] = "general"
        with patch("src.app.voice_reply", return_value=stream_of(["Hmm. "])):
            self.assertEqual(self.events(messages)[-1]["mode"], "general")

    def test_library_questions_are_spoken_from_the_file_list(self, knowledge_base, *_):
        events = self.events(self.ask("What documents do I have?"))
        self.assertEqual(events[0]["text"], "You have one document: syllabus.")
        self.assertEqual(events[-1]["mode"], "library")
        knowledge_base.return_value.retrieve.assert_not_called()

    def test_unindexed_documents_become_an_error_event(self, knowledge_base, *_):
        knowledge_base.return_value.retrieve.side_effect = DocumentError("Some documents are not indexed.")
        self.assertEqual(self.events(self.ask("When is it due?")),
                         [{"type": "error", "message": "Some documents are not indexed."}])


class VoiceLibraryTests(unittest.TestCase):
    def test_names_are_spoken_without_extensions(self):
        self.assertEqual(answering.voice_library_response("List my files", ["a_b.pdf", "c-d.md", "e.txt"]),
                         "You have 3 documents: a b, c d and e.")
        self.assertEqual(answering.voice_library_response("List my files", []),
                         "You haven't uploaded any documents yet.")
        self.assertIsNone(answering.voice_library_response("Summarize my files", ["a.pdf"]))


class VoiceAnswerTests(unittest.TestCase):
    messages = [{"role": "user", "content": "Tell me a joke"}]

    @patch("src.answering.ollama_stream")
    def test_streams_text_with_voice_settings_and_history(self, stream):
        stream.return_value = stream_of([{"message": {"content": "Why "}}, {"message": {"content": ""}},
                                    {"message": {"content": "not?"}}])
        self.assertEqual(list(answering.voice_reply(self.messages, "m")), ["Why ", "not?"])
        payload = stream.call_args.args[1]
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["options"]["num_ctx"], 16384)
        self.assertEqual(payload["options"]["temperature"], 0.7)
        self.assertEqual(payload["messages"][0]["content"], answering.VOICE_PROMPT)
        self.assertEqual(payload["messages"][1:], self.messages)

    @patch("src.answering.ollama_stream")
    def test_document_reply_streams_at_temperature_zero_with_passages(self, stream):
        stream.return_value = stream_of([{"message": {"content": "Due Friday."}}])
        self.assertEqual(list(answering.voice_document_reply("When?", [PASSAGE], "m")), ["Due Friday."])
        payload = stream.call_args.args[1]
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertNotIn("format", payload)
        self.assertEqual(payload["messages"][0]["content"], answering.VOICE_DOCUMENT_PROMPT)
        self.assertIn("December 5", payload["messages"][1]["content"])

    @patch("src.answering.ollama_stream", return_value=stream_of([{"message": "bad"}]))
    def test_malformed_stream_is_an_error(self, _):
        with self.assertRaises(ValueError):
            list(answering.voice_reply(self.messages, "m"))

    @patch("src.answering.ollama_stream")
    def test_name_questions_answer_as_yapperton_without_a_model_call(self, stream):
        for question in ("Who are you?", "Hey Yapperton, what's your name?", "what is your name"):
            reply = "".join(answering.voice_reply([{"role": "user", "content": question}], "m"))
            self.assertIn("Yapperton", reply)
        self.assertIsNone(answering.identity_response("Who are you talking about in session 3?", "m"))
        stream.assert_not_called()

    def test_requests_for_missing_abilities_are_declined_in_code(self):
        for question in ("Can you set a reminder for 5pm?", "Remind me to study", "Set an alarm for 7",
                         "Send an email to my teacher", "Schedule a meeting tomorrow", "Organize my files"):
            self.assertIn("outside what I can do", answering.identity_response(question, "m"), question)
        for question in ("When is the project meeting?", "What does the lecture say about email security?",
                         "How do reminders help memory?"):
            self.assertIsNone(answering.identity_response(question, "m"), question)

    def test_every_answer_prompt_carries_the_persona(self):
        self.assertTrue(answering.VOICE_PROMPT.startswith(answering.PERSONA))
        self.assertTrue(answering.VOICE_DOCUMENT_PROMPT.startswith(answering.PERSONA))

    @patch("src.answering.ollama_stream")
    def test_model_identity_needs_no_model_call(self, stream):
        question = [{"role": "user", "content": "What model are you?"}]
        self.assertIn("m", "".join(answering.voice_reply(question, "m")))
        stream.assert_not_called()


class OllamaStreamTests(unittest.TestCase):
    @patch("src.ollama_client.urlopen")
    def test_yields_objects_and_closes_the_connection(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value = iter([b'{"message": {"content": "A"}}\n', b'{"done": true}\n'])
        urlopen.return_value = response
        stream = ollama_client.ollama_stream("chat", {})
        self.assertEqual(next(stream), {"message": {"content": "A"}})
        response.__exit__.assert_not_called()
        stream.close()
        response.__exit__.assert_called_once()

    @patch("src.ollama_client.urlopen")
    def test_error_lines_raise(self, urlopen):
        for line in (b'{"error": "no model"}\n', b"not json\n", b"[1]\n"):
            urlopen.return_value.__enter__.return_value = iter([line])
            with self.assertRaises(ValueError):
                list(ollama_client.ollama_stream("chat", {}))


if __name__ == "__main__":
    unittest.main()
