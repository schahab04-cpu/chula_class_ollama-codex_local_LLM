import unittest
from pathlib import Path
from unittest.mock import patch

from src import ollama_service


class EnsureRunningTests(unittest.TestCase):
    @patch("src.ollama_service._start")
    @patch("src.ollama_service.running", return_value=True)
    def test_a_running_server_is_left_alone(self, _, start):
        self.assertTrue(ollama_service.ensure_running())
        start.assert_not_called()

    @patch("src.ollama_service.time.sleep")
    @patch("src.ollama_service._start")
    @patch("src.ollama_service.launch_commands", return_value=[["ollama", "serve"]])
    @patch("src.ollama_service.running", side_effect=[False, False, True])
    def test_starts_ollama_and_waits_until_it_answers(self, _, __, start, ___):
        self.assertTrue(ollama_service.ensure_running())
        start.assert_called_once_with(["ollama", "serve"])

    @patch("src.ollama_service._start")
    @patch("src.ollama_service.launch_commands", return_value=[["app"], ["ollama", "serve"]])
    @patch("src.ollama_service.running", return_value=False)
    def test_falls_back_to_the_next_command_and_reports_failure(self, _, __, start, *___):
        with self.assertLogs("src.ollama_service", level="WARNING"):
            self.assertFalse(ollama_service.ensure_running(wait_seconds=0))
        self.assertEqual([call.args[0] for call in start.call_args_list], [["app"], ["ollama", "serve"]])

    @patch("src.ollama_service.launch_commands", return_value=[])
    @patch("src.ollama_service.running", return_value=False)
    def test_missing_installation_is_reported(self, *_):
        with self.assertLogs("src.ollama_service", level="WARNING") as logs:
            self.assertFalse(ollama_service.ensure_running())
        self.assertIn("ollama.com", logs.output[0])


class LaunchCommandTests(unittest.TestCase):
    @patch("src.ollama_service.shutil.which", return_value="/usr/local/bin/ollama")
    @patch("src.ollama_service.Path.is_dir", return_value=True)
    @patch("src.ollama_service.sys.platform", "darwin")
    def test_macos_prefers_the_desktop_app(self, *_):
        self.assertEqual(ollama_service.launch_commands(),
                         [["open", "-g", "-a", "Ollama"], ["/usr/local/bin/ollama", "serve"]])

    @patch("src.ollama_service.shutil.which", return_value=None)
    @patch("src.ollama_service.Path.is_file", return_value=True)
    @patch("src.ollama_service.WINDOWS", True)
    @patch("src.ollama_service.sys.platform", "win32")
    def test_windows_uses_the_installed_app_then_its_server(self, *_):
        with patch.dict("os.environ", {"LOCALAPPDATA": "C:/Users/me/AppData/Local"}):
            commands = ollama_service.launch_commands()
        folder = Path("C:/Users/me/AppData/Local/Programs/Ollama")
        self.assertEqual(commands, [[str(folder / "ollama app.exe")], [str(folder / "ollama.exe"), "serve"]])


class MissingModelTests(unittest.TestCase):
    @patch("src.ollama_service.urlopen")
    def test_lists_models_that_are_not_installed(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = (
            b'{"models": [{"name": "qwen3.5:9b"}]}')
        self.assertEqual(ollama_service.missing_models(["qwen3.5:9b", "nomic-embed-text:latest"]),
                         ["nomic-embed-text:latest"])

    @patch("src.ollama_service.urlopen", side_effect=OSError("down"))
    def test_unreachable_ollama_reports_nothing_missing(self, _):
        self.assertEqual(ollama_service.missing_models(["qwen3.5:9b"]), [])


if __name__ == "__main__":
    unittest.main()
