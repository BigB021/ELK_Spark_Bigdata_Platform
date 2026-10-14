"""Prints the HTML report to PDF with Playwright + installed Edge (A4, page numbers).

usage: python scripts/render_report_pdf.py <report.html> <output.pdf>
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

FOOTER = ('<div style="font-size:8px;color:#888;width:100%;padding:0 16mm;display:flex;'
          'justify-content:space-between"><span>TP4 - Pipeline Logstash · Plateforme ED</span>'
          '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')

src, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page()
    page.goto(src.as_uri(), wait_until="load")
    page.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=True,
             display_header_footer=True, header_template="<span></span>", footer_template=FOOTER,
             margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"})
    browser.close()
print(f"PDF -> {out}")
