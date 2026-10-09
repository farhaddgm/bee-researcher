"""Content-addressed trusted UI modules; no arbitrary path or user code.

Retain script ordering and global lexical scope. Assets are immutable and
public UI code only; per-request identity/configuration stays in the document.
"""
from functools import lru_cache
import hashlib
import re

ASSETS: dict[str, tuple[str, str]] = {}
_BLOCK = re.compile(r'<(script|style)([^>]*)>([\s\S]*?)</\1>')


@lru_cache(maxsize=8)
def externalize_document(html: str) -> str:
    def replace(match):
        kind, attributes, code = match.groups()
        if kind == 'script' and re.search(r'\bsrc\s*=', attributes):
            return match.group(0)
        # Non-executable JSON configuration must not become JavaScript.
        if kind == 'script' and 'application/json' in attributes:
            return match.group(0)
        extension = 'js' if kind == 'script' else 'css'
        name = hashlib.sha256(code.encode()).hexdigest() + '.' + extension
        ASSETS[name] = (code, 'text/javascript' if kind == 'script' else 'text/css')
        if kind == 'script':
            return '<script' + attributes + ' src="/assets/ui/' + name + '"></script>'
        return '<link rel="stylesheet"' + attributes + ' href="/assets/ui/' + name + '">'
    return _BLOCK.sub(replace, html)
