"""Regression for Windows registry MIME overrides rejecting PWA scripts."""
from contextlib import redirect_stderr
from http.server import SimpleHTTPRequestHandler
import io
import mimetypes
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from serve_web import WebAppHandler
from test_web import QuietHandler


class MemoryConnection:
    """Exercise the HTTP handler without binding a local socket."""

    def __init__(self, path):
        self.request = io.BytesIO(
            f'GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode('ascii'))
        self.response = bytearray()

    def makefile(self, mode, buffering=-1):
        return self.request

    def sendall(self, data):
        self.response.extend(data)


def request_file(handler, directory, path):
    connection = MemoryConnection(path)
    with redirect_stderr(io.StringIO()):
        handler(connection, ('127.0.0.1', 12345), object(), directory=str(directory))
    headers, body = bytes(connection.response).split(b'\r\n\r\n', 1)
    return headers.decode('ascii'), body


class ScriptMimeTests(unittest.TestCase):
    def test_script_headers_ignore_host_mime_overrides(self):
        mimetypes.init()
        script = b'self.addEventListener("install", () => self.skipWaiting());\n'
        with tempfile.TemporaryDirectory() as directory:
            for name in ('sw.js', 'module.mjs', 'upper.JS'):
                Path(directory, name).write_bytes(script)
            with patch.dict(mimetypes.types_map, {'.js': 'text/plain', '.mjs': 'text/plain'}):
                # Confirm this fixture reproduces the host-level regression.
                headers, _ = request_file(SimpleHTTPRequestHandler, directory, '/sw.js')
                self.assertIn('Content-type: text/plain', headers)
                for handler in (WebAppHandler, QuietHandler):
                    for name in ('sw.js', 'module.mjs', 'upper.JS'):
                        with self.subTest(handler=handler.__name__, file=name):
                            headers, body = request_file(handler, directory, '/' + name)
                            self.assertTrue(headers.startswith('HTTP/1.0 200 '))
                            self.assertIn('Content-type: text/javascript', headers)
                            self.assertEqual(body, script)

    def test_non_script_types_keep_normal_resolution(self):
        mimetypes.init()
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'sample.casebooktest').write_bytes(b'unchanged')
            with patch.dict(mimetypes.types_map, {'.casebooktest': 'application/x-casebook-test'}):
                for handler in (WebAppHandler, QuietHandler):
                    with self.subTest(handler=handler.__name__):
                        headers, body = request_file(handler, directory, '/sample.casebooktest')
                        self.assertIn('Content-type: application/x-casebook-test', headers)
                        self.assertEqual(body, b'unchanged')


if __name__ == '__main__':
    unittest.main()
