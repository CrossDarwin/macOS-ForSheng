# SPDX-License-Identifier: MIT
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from range_download import download

DATA = b'abcdef0123456789' * 4096


class Handler(BaseHTTPRequestHandler):
    ignore_range = False

    def log_message(self, *_):
        pass

    def do_GET(self):
        start, end = map(int, self.headers['Range'].removeprefix('bytes=').split('-'))
        if self.ignore_range:
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(206)
        self.send_header('Content-Range', f'bytes {start}-{end}/{len(DATA)}')
        self.end_headers()
        self.wfile.write(DATA[start:end+1])


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/input'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_download_resume_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.part'
            path.write_bytes(DATA[:100])
            download(self.url, path, len(DATA), 2)
            self.assertEqual(path.read_bytes(), DATA)
            download(self.url, path, len(DATA), 2)
            with self.assertRaises(ValueError):
                download(self.url + '/changed', path, len(DATA), 2)

    def test_range_ignored_is_rejected(self):
        self.server.RequestHandlerClass = type('IgnoringHandler', (Handler,), {'ignore_range': True})
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, 'exact byte range'):
            download(self.url, Path(directory) / 'input.part', len(DATA), 2)
