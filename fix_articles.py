#!/usr/bin/env python3
"""Fix all article pages in learn/ directory:
  - Replace old emoji nav with full SVG nav
  - Replace old footer with SVG footer, neutral language, no app link
  - Remove app.fintiq.uk from meta lines and CTA boxes
  - Fix non-www fintiq.uk href links
  - Remove 'UK investors' / 'UK Markets' language
"""
import os, re

LEARN_DIR = os.path.join(os.path.dirname(__file__), "learn")

NEW_NAV = '<nav><a href="https://www.fintiq.uk/" class="logo" style="display:flex;align-items:center;gap:8px"><svg width="28" height="28" viewBox="0 0 28 28" fill="none"><line x1="5" y1="17" x2="5" y2="21" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/><rect x="3" y="21" width="4" height="4" rx="0.8" fill="#22c55e"/><line x1="14" y1="9" x2="14" y2="13" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/><rect x="12" y="13" width="4" height="6" rx="0.8" fill="#22c55e"/><line x1="23" y1="3" x2="23" y2="7" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/><rect x="21" y="7" width="4" height="9" rx="0.8" fill="#22c55e"/><polyline points="5,20 14,14 23,8" stroke="#22c55e" stroke-width="1.5" fill="none" opacity="0.5"/></svg>Fintiq</a><div class="nav-links"><a href="https://www.fintiq.uk/">Home</a><a href="https://www.fintiq.uk/bulletin.html">Market Bulletin</a><a href="https://www.fintiq.uk/deep-dive.html">Stock Deep Dive</a><a href="https://www.fintiq.uk/tools.html">Tools</a><a href="https://www.fintiq.uk/learn.html" style="color:#F59E0B">Learn</a></div></nav>'

NEW_FOOTER = '''<footer>
<div class="f-logo" style="display:flex;align-items:center;justify-content:center;gap:8px"><svg width="24" height="24" viewBox="0 0 28 28" fill="none"><line x1="5" y1="17" x2="5" y2="21" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/><rect x="3" y="21" width="4" height="4" rx="0.8" fill="#22c55e"/><line x1="14" y1="9" x2="14" y2="13" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/><rect x="12" y="13" width="4" height="6" rx="0.8" fill="#22c55e"/><line x1="23" y1="3" x2="23" y2="7" stroke="#22c55e" stroke-width="2" stroke-linecap="round"/><rect x="21" y="7" width="4" height="9" rx="0.8" fill="#22c55e"/><polyline points="5,20 14,14 23,8" stroke="#22c55e" stroke-width="1.5" fill="none" opacity="0.5"/></svg>Fintiq</div>
<div class="f-sub">Professional investing tools and guides for investors worldwide</div>
<div class="f-links"><a href="https://www.fintiq.uk/">Home</a><a href="https://www.fintiq.uk/tools.html">Tools</a><a href="https://www.fintiq.uk/learn.html">Learn</a></div>
<div class="f-copy">&copy; 2026 Fintiq. Educational content only. Not financial advice.</div>
</footer>'''

def fix_file(path):
    # Try UTF-8 first, fall back to cp1252 for Windows-encoded files
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            with open(path, 'r', encoding=enc) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue
    original = content

    # 1. Replace nav — handles both &#128202; and actual emoji 📊, both inline and multiline
    content = re.sub(r'<nav>.*?(?:&#128202;|📊) Fintiq.*?</nav>', NEW_NAV, content, flags=re.DOTALL)

    # 2. Replace footer — consistent pattern across all articles
    content = re.sub(
        r'<footer>\s*<div class="f-logo">.*?</div>\s*<div class="f-sub">.*?</div>\s*<div class="f-links">.*?</div>\s*<div class="f-copy">.*?</div>\s*</footer>',
        NEW_FOOTER,
        content,
        flags=re.DOTALL
    )

    # 3. Fix breadcrumb non-www href
    content = content.replace('href="https://fintiq.uk"', 'href="https://www.fintiq.uk/"')
    content = content.replace("href='https://fintiq.uk'", "href='https://www.fintiq.uk/'")

    # 4. Remove app.fintiq.uk from meta read lines (e.g. "· <a href="https://app.fintiq.uk"...>Try Fintiq Free</a>")
    content = re.sub(r'\s*&middot;\s*<a href="https://app\.fintiq\.uk"[^>]*>[^<]*</a>', '', content)
    content = re.sub(r'\s*·\s*<a href="https://app\.fintiq\.uk"[^>]*>[^<]*</a>', '', content)

    # 5. Replace CTA buttons pointing to app.fintiq.uk with tools page
    content = re.sub(
        r'<a href="https://app\.fintiq\.uk"([^>]*class="cta-btn"[^>]*)>[^<]*</a>',
        '<a href="https://www.fintiq.uk/tools.html"\\1>Explore the Tools &rarr;</a>',
        content
    )
    content = re.sub(
        r'<a href="https://app\.fintiq\.uk"([^>]*)class="cta-btn"([^>]*)>[^<]*</a>',
        '<a href="https://www.fintiq.uk/tools.html"\\1class="cta-btn"\\2>Explore the Tools &rarr;</a>',
        content
    )
    # Also handle CTA buttons where class comes before href
    content = re.sub(
        r'<a([^>]*)href="https://app\.fintiq\.uk"([^>]*class="cta-btn"[^>]*)>[^<]*</a>',
        '<a\\1href="https://www.fintiq.uk/tools.html"\\2>Explore the Tools &rarr;</a>',
        content
    )

    # 6. Any remaining inline app.fintiq.uk body text links → tools page
    content = re.sub(
        r'href="https://app\.fintiq\.uk[^"]*"',
        'href="https://www.fintiq.uk/tools.html"',
        content
    )

    # 7. Remove "free" from meta descriptions and keywords (not from article body to avoid false positives)
    content = re.sub(r'(content="[^"]*)\bfree\b([^"]*")', lambda m: m.group(1) + m.group(2), content, flags=re.IGNORECASE)
    # Fix keywords with "UK" in meta/keywords tags
    content = re.sub(r'(content="[^"]*)\bUK investors\b([^"]*")', r'\1investors\2', content, flags=re.IGNORECASE)

    # 8. Replace badge-free HTML badge spans (the CSS class is harmless if unused)
    content = re.sub(
        r'<span class="badge badge-free">.*?</span>',
        '<span class="badge badge-topic">Guide</span>',
        content
    )

    # 9. Remove "Free" text from CTA boxes (e.g. "Free to use", "Try Fintiq Free")
    content = re.sub(r'\bFree to use[\.!]?\s*', '', content)
    content = re.sub(r'\bTry Fintiq Free\b', 'Explore Fintiq', content)

    # 10. Fix UK-specific language in page body
    content = content.replace('for UK investors', 'for investors worldwide')
    content = content.replace('UK retail investors', 'investors')
    content = content.replace('UK Markets &amp; Strategies', 'Markets &amp; Strategies')
    content = content.replace('UK Markets', 'Markets')
    content = content.replace('UK market', 'the market')
    content = content.replace(' UK broker', ' broker')

    if content != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  UPDATED: {os.path.basename(path)}")
    else:
        print(f"  no change: {os.path.basename(path)}")

changed = 0
for fname in sorted(os.listdir(LEARN_DIR)):
    if fname.endswith('.html'):
        fix_file(os.path.join(LEARN_DIR, fname))
        changed += 1

print(f"\nDone. Processed {changed} files.")
