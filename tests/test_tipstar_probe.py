import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from probe_tipstar import inspect_html, validate_url, fetch_once

URL = 'https://tipstar.com/user/keirin/2026-10-16_12_05/race_predictors'


class DummyResponse:
    headers = {'Content-Type': 'text/html; charset=utf-8'}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, n):
        return b'<html><body>hello</body></html>'[:n]


class DummyOpener:
    calls = 0
    def open(self, req, timeout=0):
        self.calls += 1
        return DummyResponse()


class ProbeTest(unittest.TestCase):
    def test_valid_url(self):
        self.assertEqual(validate_url(URL), URL)
        self.assertEqual(validate_url(URL + '/aa28808f-f1d2-4e8b-a32a-2a10e39cacbf'), URL + '/aa28808f-f1d2-4e8b-a32a-2a10e39cacbf')

    def test_invalid_url(self):
        for url in ('http://tipstar.com/user/keirin/2026-10-16_12_05/race_predictors',
                    'https://tipstar.com.evil.test/user/keirin/2026-10-16_12_05/race_predictors',
                    'https://tipstar.com/user/account',
                    URL+'?p=1'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_parse_visible_only(self):
        html = b'<html><body><div>\xe5\x9b\x9e\xe5\x8f\x8e\xe7\x8e\x87 125%</div><a href="/x/race_predictors/abc">Link</a><script>\xe5\x9b\x9e\xe5\x8f\x8e\xe7\x8e\x87 999%</script></body></html>'
        result = inspect_html(html)
        self.assertEqual(result['rate_mentions'], 1)
        self.assertEqual(result['prediction_detail_links'], 1)

    def test_rate_limit(self):
        with tempfile.TemporaryDirectory() as path:
            marker = Path(path) / '.last'
            client = DummyOpener()
            fetch_once(URL, marker, clock=lambda: 1000, opener=client)
            with self.assertRaisesRegex(ValueError, '再取得'):
                fetch_once(URL, marker, clock=lambda: 1060, opener=client)
            self.assertEqual(client.calls, 1)
            fetch_once(URL, marker, clock=lambda: 1121, opener=client)
            self.assertEqual(client.calls, 2)


if __name__ == '__main__':
    unittest.main()
