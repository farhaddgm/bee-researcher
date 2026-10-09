"""Inspect the actual trusted source bundle behind an externalized document.

Legacy string contracts examine code rather than DOM behaviour. Keep that
scope explicit; dedicated HTTP/browser tests verify real external asset loads.
"""
import re
from app.ui_assets import ASSETS


def document_source(html):
    def script(match):
        attrs, name = match.groups()
        return '<script' + attrs + '>' + ASSETS[name][0] + '</script>'
    def style(match):
        attrs, name = match.groups()
        attrs = attrs.replace(' rel="stylesheet"', '')
        return '<style' + attrs + '>' + ASSETS[name][0] + '</style>'
    html = re.sub(r'<script([^>]*?) src="/assets/ui/([\w.]+)"></script>', script, html)
    return re.sub(r'<link([^>]*?) href="/assets/ui/([\w.]+)">', style, html)
