"""PNG screenshots for the report: Kibana pages + terminal evidence pages.

Requires Playwright and the installed Microsoft Edge:
    pip install playwright        (no browser download needed: channel="msedge")
usage: python scripts/capture_screenshots.py <deliverable_dir>/6_captures
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
KB = "http://localhost:5601"
G = "_g=(time:(from:now-2y,to:now))"

KIBANA = [  # name, url, viewport height
    ("12_kibana_discover_visits",
     f"{KB}/app/discover#/?{G}&_a=(dataSource:(dataViewId:ed-visits,type:dataView),query:(language:kuery,query:'ingest.run_id%20:%20%22main%22'))", 1000),
    ("13_kibana_discover_warning",
     f"{KB}/app/discover#/?{G}&_a=(dataSource:(dataViewId:ed-visits,type:dataView),query:(language:kuery,query:'dq.status%20:%20%22warning%22%20and%20ingest.run_id%20:%20%22main%22'))", 1000),
    ("14_kibana_discover_rejects",
     f"{KB}/app/discover#/?{G}&_a=(dataSource:(dataViewId:ed-rejects,type:dataView),query:(language:kuery,query:'ingest.run_id%20:%20%22main%22'))", 1000),
    ("15_kibana_dashboard_activite", f"{KB}/app/dashboards#/view/ed-dashboard-activity", 1450),
    ("16_kibana_dashboard_qualite", f"{KB}/app/dashboards#/view/ed-dashboard-quality", 920),
    ("17_kibana_index_management", f"{KB}/app/management/data/index_management/indices?filter=ed-", 700),
    ("18_kibana_data_view_fields", f"{KB}/app/management/kibana/dataViews/dataView/ed-visits", 1300),
]


def wait_rendered(page, budget=90):
    deadline = time.time() + budget
    while time.time() < deadline:
        n = page.locator("[data-render-complete]").count()
        done = page.locator("[data-render-complete='true']").count()
        if n and done >= n:
            break
        time.sleep(1)
    time.sleep(4)
    for b in page.locator("[data-test-subj='toastCloseButton']").all():
        try:
            b.click(timeout=1000)
        except Exception:
            pass


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        # terminal evidence pages -> PNG (height fitted to content)
        for html_file in sorted((OUT / "preuves_texte" / "html").glob("*.html")):
            page = browser.new_page(viewport={"width": 1250, "height": 400})
            page.goto(html_file.resolve().as_uri())
            page.screenshot(path=str(OUT / f"{html_file.stem}.png"), full_page=True)
            page.close()
            print("terminal", html_file.stem)
        for name, url, height in KIBANA:
            page = browser.new_page(viewport={"width": 1600, "height": height})
            page.goto(url, wait_until="domcontentloaded")
            wait_rendered(page)
            page.screenshot(path=str(OUT / f"{name}.png"))
            page.close()
            print("kibana", name)
        browser.close()


if __name__ == "__main__":
    main()
