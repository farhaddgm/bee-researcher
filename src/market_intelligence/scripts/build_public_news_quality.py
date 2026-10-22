"""Build an explicit public-news QA packet from downloaded official NASA feeds.

No network, credentials, production news or publishing side effects. Excerpts
are deliberately labelled as excerpts; evaluation must not claim full coverage.
"""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style'} and self.hidden:
            self.hidden -= 1

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def build(paths):
    entries = []
    seen = set()
    for path in paths:
        if path.stat().st_size > 5_000_000:
            raise ValueError('feed_too_large')
        root = ET.fromstring(path.read_bytes())
        for item in root.findall('./channel/item'):
            url = item.findtext('link') or ''
            host = urlparse(url).hostname or ''
            if urlparse(url).scheme != 'https' or not (host == 'nasa.gov' or host.endswith('.nasa.gov')):
                raise ValueError('unapproved_public_publisher')
            if url in seen:
                continue
            parser = PlainText()
            parser.feed(item.findtext('{http://purl.org/rss/1.0/modules/content/}encoded') or item.findtext('description') or '')
            text = ' '.join(' '.join(parser.parts).split())[:8000]
            if len(text) < 100:
                raise ValueError('public_excerpt_too_short')
            entries.append({'id':hashlib.sha256(url.encode()).hexdigest()[:16], 'url':url,
                            'title':item.findtext('title') or '', 'published_at':item.findtext('pubDate'),
                            'text':text, 'excerpt':True, 'publisher':'NASA'})
            seen.add(url)
    if len(entries) != 40:
        raise ValueError('exactly_40_distinct_public_reports_required')
    return {'schema_version':1, 'data_scope':'public_publisher_excerpts_only', 'human_review':False,
            'entries':entries, 'source_digest':hashlib.sha256(json.dumps(entries,sort_keys=True).encode()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('feeds', type=Path, nargs='+')
    print(json.dumps(build(parser.parse_args().feeds), ensure_ascii=False, indent=2))
