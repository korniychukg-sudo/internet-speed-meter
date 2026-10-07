import http.server
import io
import sys
import threading
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import speedmeter

PAYLOAD = b"x" * 2_000_000


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/missing":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)

    def log_message(self, *args):
        pass


class FakeClock:
    def __init__(self, step):
        self.now = 0.0
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


class SummaryMathTest(unittest.TestCase):
    def test_average_and_speed(self):
        clock = FakeClock(step=0.5)
        summary = speedmeter.measure("http://x", count=4, fetch=lambda url, t: 1_000_000, clock=clock)
        self.assertEqual(len(summary.successful), 4)
        self.assertAlmostEqual(summary.average_seconds, 0.5)
        self.assertEqual(summary.total_bytes, 4_000_000)
        self.assertAlmostEqual(summary.megabytes_per_second, 2.0)
        self.assertAlmostEqual(summary.megabits_per_second, 16.0)

    def test_failed_attempts_are_excluded(self):
        calls = {"n": 0}

        def flaky(url, timeout):
            calls["n"] += 1
            if calls["n"] % 2 == 0:
                raise urllib.error.URLError("timed out")
            return 500_000

        summary = speedmeter.measure("http://x", count=4, fetch=flaky, clock=FakeClock(step=1.0))
        self.assertEqual(len(summary.attempts), 4)
        self.assertEqual(len(summary.successful), 2)
        self.assertEqual(summary.total_bytes, 1_000_000)
        self.assertAlmostEqual(summary.megabytes_per_second, 0.5)
        self.assertIn("сетевая ошибка", summary.attempts[1].error)

    def test_requests_are_sequential(self):
        active = {"now": 0, "max": 0}

        def fetch(url, timeout):
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
            active["now"] -= 1
            return 1

        speedmeter.measure("http://x", count=10, fetch=fetch)
        self.assertEqual(active["max"], 1)


class ArgsTest(unittest.TestCase):
    def test_defaults(self):
        args = speedmeter.parse_args([])
        self.assertEqual(args.count, 10)
        self.assertTrue(args.url.startswith("https://"))

    def test_rejects_bad_input(self):
        for argv in (["ftp://host/file"], ["-n", "0"], ["-t", "0"]):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                    speedmeter.parse_args(argv)


class LocalServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_downloads_full_body_ten_times(self):
        summary = speedmeter.measure(self.base + "/image.jpg", count=10, timeout=5)
        self.assertEqual(len(summary.successful), 10)
        self.assertEqual(summary.total_bytes, 10 * len(PAYLOAD))
        self.assertGreater(summary.megabytes_per_second, 0)

    def test_http_error_is_reported(self):
        summary = speedmeter.measure(self.base + "/missing", count=2, timeout=5)
        self.assertEqual(len(summary.successful), 0)
        self.assertEqual(summary.attempts[0].error, "HTTP 404")

    def test_main_prints_speed(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = speedmeter.main([self.base + "/image.jpg", "-n", "3", "-t", "5"])
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Успешных запросов: 3 из 3", text)
        self.assertIn("МБ/с", text)

    def test_main_exit_code_when_all_fail(self):
        with redirect_stdout(io.StringIO()):
            code = speedmeter.main([self.base + "/missing", "-n", "2", "-t", "5"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
