import io
import json
import unittest
import wave
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from src import answering, ollama_client, speech
from src.app import VOICE_LIMIT, app


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

    @patch("src.app.warm_up_voice_model")
    @patch("src.speech.warm_up")
    def test_warmup_reports_missing_ollama(self, _, warm_model):
        self.assertEqual(self.client.post("/api/voice/warmup").status_code, 204)
        warm_model.side_effect = URLError("down")
        self.assertEqual(self.client.post("/api/voice/warmup").status_code, 503)

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

    @patch("src.answering.ollama_stream", return_value=stream_of([{"message": "bad"}]))
    def test_malformed_stream_is_an_error(self, _):
        with self.assertRaises(ValueError):
            list(answering.voice_reply(self.messages, "m"))

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
