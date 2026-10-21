#!/usr/local/bin/python
# -*- coding: utf-8 -*-
"""Bounded public TIPSTAR page probe. No login, batch crawling or DB writes.

This tool only checks whether a single explicitly specified public race-predictors
page is accessible and reports structural indicators. It never saves HTML,
predictor names, sessions or cookies. Permission is needed before collection
and permanent storage of TIPSTAR content.
"""
import argparse
import fcntl
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
LIMIT_BYTES = 750000
MIN_INTERVAL_SEC = 120
HOSTS = ('tipstar.com', 'www.tipstar.com')
PATH = re.compile(r'/user/keirin/\d{4}-\d{2}-\d{2}_\d{2}_\d{2}/race_predictors(?:/[0-9a-f-]{36})?/?\Z', re.I)


def validate_url(url):
    u = urlsplit(url)
    if (u.scheme != 'https' or u.hostname not in HOSTS
            or u.username is not None or u.password is not None
            or u.port not in (None, 443) or u.query or u.fragment
            or not PATH.fullmatch(u.path)):
        raise ValueError('TIPSTARの公開 race_predictors URLのみ指定できます')
    return url


class SameSiteRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ExtractText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.text = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.skip += 1
        if tag == 'a':
            for k, v in attrs:
                if k == 'href' and v and '/race_predictors/' in v:
                    self.links.append(v)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.text.append(data.strip())


def inspect_html(raw):
    if len(raw) > LIMIT_BYTES:
        raise ValueError('応答がサイズ上限を超えました')
    try:
        html = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('UTF-8 HTML以外の応答です')
    p = ExtractText()
    p.feed(html)
    visible = ' '.join(p.text)
    # Indicators only: parsed counts are NOT per-tipster observations.
    rates = re.findall(r'回収率\s*([0-9]{1,5})\s*%', visible)
    return {
        'bytes': len(raw),
        'visible_text_characters': len(visible),
        'rate_mentions': len(rates),
        'prediction_detail_links': len(set(p.links)),
        'client_rendered_possible': len(visible) < 150,
        'note': '構造診断のみ。予想師の同一性や実際の回収率は確定していません。'
    }


def fetch_once(url, marker, clock=time.time, opener=None):
    """System-wide throttle on this host using an advisory BSD file lock."""
    validate_url(url)
    marker.parent.mkdir(parents=True, exist_ok=True)
    opener = opener or build_opener(SameSiteRedirect())
    with marker.open('a+', encoding='ascii') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.seek(0)
        try:
            last = float(f.read().strip() or '0')
        except ValueError:
            last = 0
        at = clock()
        if at - last < MIN_INTERVAL_SEC:
            raise ValueError('再取得まであと {} 秒必要です'.format(int(MIN_INTERVAL_SEC - (at-last)) + 1))
        # Reserve the interval BEFORE sending HTTP request, even on failures.
        f.seek(0)
        f.truncate()
        f.write(str(at))
        f.flush()
        req = Request(url, headers={
            'User-Agent': 'KEIRIN-LAB-research/0.1 (single-public-page-probe)',
            'Accept': 'text/html'
        })
        with opener.open(req, timeout=12) as resp:
            media = resp.headers.get('Content-Type', '')
            if 'text/html' not in media:
                raise ValueError('HTMLではない応答です: ' + media[:100])
            raw = resp.read(LIMIT_BYTES + 1)
        if len(raw) > LIMIT_BYTES:
            raise ValueError('応答がサイズ上限を超えました')
    return inspect_html(raw)


def main(argv=None):
    ap = argparse.ArgumentParser(description='TIPSTAR公開ページの低頻度・単発取得診断')
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument('--url', help='TIPSTAR公開race_predictors URL')
    grp.add_argument('--fixture', type=Path, help='ローカルHTMLでパーサを診断（外部通信なし）')
    args = ap.parse_args(argv)
    try:
        if args.fixture:
            info = inspect_html(args.fixture.read_bytes())
        else:
            info = fetch_once(args.url, ROOT / 'data' / '.tipstar_probe_last')
        print(json.dumps(info, ensure_ascii=False, indent=2))
        if info['client_rendered_possible']:
            print('注記: ページがJavaScript描画の場合、この診断では内容を取得できません。', file=sys.stderr)
        return 0
    except HTTPError as e:
        print('HTTP {}: アクセスを継続せず停止しました。'.format(e.code), file=sys.stderr)
    except (URLError, ValueError, OSError) as e:
        print('取得停止: {}'.format(e), file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
