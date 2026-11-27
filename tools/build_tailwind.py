#!/usr/bin/env python3
"""
Rebuilds server/web/tailwind.css (the dashboard's pre-built styles).

Run this after adding new Tailwind classes to index.html or app.js:
    /usr/bin/python3 tools/build_tailwind.py
then open http://127.0.0.1:8798/ in any browser. The page lets Tailwind
generate CSS for every class the dashboard uses and saves it automatically.
Needs internet for that one step only; the app itself never needs it.
"""
import http.server
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "server", "web")
OUT = os.path.join(WEB, "tailwind.css")
PORT = 8798


def collect_classes():
    tokens = set()
    html = open(os.path.join(WEB, "index.html")).read()
    for attr in re.findall(r'class="([^"]*)"', html):
        tokens.update(attr.split())
    js = open(os.path.join(WEB, "app.js")).read()
    # every word inside JS strings/templates that looks like a CSS class
    for lit in re.findall(r"'([^'\n]*)'|`([^`]*)`|\"([^\"\n]*)\"", js):
        text = " ".join(x for x in lit if x)
        text = re.sub(r"\$\{[^}]*\}", " ", text)
        for t in text.split():
            if re.fullmatch(r"[!a-z0-9:\-/\[\]\.#%()_,]+", t) and any(c.isalpha() for c in t):
                tokens.add(t)
    return sorted(tokens)


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script src="https://cdn.tailwindcss.com/3.4.17"></script></head>
<body><div id="all" style="display:none" class="%s"></div>
<pre id="msg">Generating...</pre>
<script>
setTimeout(async () => {
  const styles = [...document.querySelectorAll('style')].map(s => s.textContent);
  const css = styles.sort((a, b) => b.length - a.length)[0] || '';
  const r = await fetch('/save', {method: 'POST', body: css});
  document.getElementById('msg').textContent = await r.text();
}, 2500);
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = (PAGE % " ".join(collect_classes())).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        css = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        if len(css) < 1000:
            msg = "Generation failed (empty CSS). Check internet and reload."
        else:
            header = "/* Pre-built Tailwind CSS for the dashboard. Rebuild with tools/build_tailwind.py */\n"
            open(OUT, "w").write(header + css)
            msg = f"Saved {len(css)//1024} KB to server/web/tailwind.css - you can close this."
            print(msg)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(msg.encode())
        if len(css) >= 1000:
            os._exit(0)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Open http://127.0.0.1:{PORT}/ to build ({len(collect_classes())} classes found)")
    http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
