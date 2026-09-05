"""The published page: one self-contained HTML file per run, plus a day snapshot.

Layer 5. It reads what `store.day_matches()` hands back and writes
`<data_dir>/index.html` and `<data_dir>/days/<local date>.html`. Both files are
whole: the CSS and the JavaScript are inline and there is not one external
asset on the page. A radar whose report needs a CDN stops being readable exactly
when the network is the thing you wanted to read about.

Templating is f-strings, not an engine. One page does not earn a dependency
(docs/memory-ai/architecture/module-layout.md, stack table).

Everything that came off a feed - titles, links, source ids - goes through
`html.escape` on its way in. This is the trust boundary: a feed title is
somebody else's text, and it arrives unreviewed every thirty minutes.

Contract: docs/memory-ai/data/news-item.md (output layout)
"""

from __future__ import annotations

import datetime as dt
import html
import logging

from pathlib import Path
from zoneinfo import ZoneInfo

__all__ = ["local_tz", "day_bounds", "write", "DAYS_DIR"]

log = logging.getLogger("news_radar.render")

DAYS_DIR = "days"
INDEX_NAME = "index.html"

# Zone names already reported as unresolvable. Without it the fallback below
# logs the same line every thirty minutes forever.
_WARNED = set()

STYLE = """
:root {
  color-scheme: light;
  --bg: #f6f7f9; --card: #ffffff; --ink: #16191d; --dim: #6b7280;
  --line: #e3e6ea; --hot: #b45309; --hot-bg: #fff7ed; --link: #1d4ed8;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #0f1115; --card: #171a20; --ink: #e6e8ec; --dim: #98a1ad;
    --line: #262b33; --hot: #fbbf24; --hot-bg: #221a08; --link: #7aa2f7;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #0f1115; --card: #171a20; --ink: #e6e8ec; --dim: #98a1ad;
  --line: #262b33; --hot: #fbbf24; --hot-bg: #221a08; --link: #7aa2f7;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
header, main, footer { max-width: 62rem; margin: 0 auto; padding: 0 1rem; }
header { padding-top: 1.5rem; }
h1 { margin: 0 0 .25rem; font-size: 1.4rem; letter-spacing: -.01em; }
h1 .day { color: var(--dim); font-weight: 400; }
.bar { display: flex; gap: .5rem; margin: 1rem 0 .75rem; }
#q {
  flex: 1; padding: .55rem .75rem; border: 1px solid var(--line);
  border-radius: .5rem; background: var(--card); color: inherit; font: inherit;
}
#theme {
  padding: .55rem .8rem; border: 1px solid var(--line); border-radius: .5rem;
  background: var(--card); color: inherit; font: inherit; cursor: pointer;
}
nav.days { display: flex; flex-wrap: wrap; gap: .4rem; font-size: .85rem; }
nav.days a {
  padding: .2rem .5rem; border: 1px solid var(--line); border-radius: .4rem;
  color: var(--dim); text-decoration: none;
}
nav.days a[aria-current="page"] { color: var(--ink); border-color: var(--dim); }
section.group {
  background: var(--card); border: 1px solid var(--line);
  border-radius: .6rem; margin: 1rem 0; padding: .25rem 1rem 1rem;
}
section.group h2 {
  font-size: 1rem; margin: .9rem 0 .5rem; display: flex; gap: .5rem;
  align-items: baseline;
}
section.group h2 .n { color: var(--dim); font-weight: 400; font-size: .85rem; }
ol.stories { list-style: none; margin: 0; padding: 0; }
li.story { padding: .45rem 0; border-top: 1px solid var(--line); }
li.story:first-child { border-top: 0; }
li.story.hot { border-left: 3px solid var(--hot); padding-left: .6rem;
               background: var(--hot-bg); }
li.story a { color: var(--link); text-decoration: none; }
li.story a:hover { text-decoration: underline; }
li.story .meta {
  display: block; color: var(--dim); font-size: .8rem; margin-top: .15rem;
}
li.story.hot .score { color: var(--hot); font-weight: 600; }
p.empty { color: var(--dim); font-style: italic; margin: .4rem 0 .6rem; }
section.summary {
  background: var(--card); border: 1px solid var(--line);
  border-left: 3px solid var(--dim);
  border-radius: .6rem; margin: 1rem 0; padding: .75rem 1rem;
}
section.summary p { margin: .35rem 0; }
section.summary strong { color: var(--hot); }
footer { color: var(--dim); font-size: .8rem; padding: 1rem; text-align: center; }
"""

SCRIPT = """
(function () {
  var root = document.documentElement, KEY = 'news-radar-theme';
  try {
    var saved = localStorage.getItem(KEY);
    if (saved) { root.setAttribute('data-theme', saved); }
  } catch (e) { /* private mode: the page still works, it just forgets */ }

  document.getElementById('theme').addEventListener('click', function () {
    var dark = root.getAttribute('data-theme') === 'dark'
      || (!root.getAttribute('data-theme')
          && matchMedia('(prefers-color-scheme: dark)').matches);
    var next = dark ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem(KEY, next); } catch (e) {}
  });

  // The same folding the matcher uses, so a search typed "dien tu" finds
  // "Dien tu" written with its diacritics.
  function fold(s) {
    return s.toLowerCase().replace(/\\u0111/g, 'd')
            .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
  }

  var q = document.getElementById('q');
  q.addEventListener('input', function () {
    var needle = fold(q.value.trim());
    document.querySelectorAll('section.group').forEach(function (sec) {
      var shown = 0;
      sec.querySelectorAll('li.story').forEach(function (li) {
        var hit = !needle || fold(li.textContent).indexOf(needle) > -1;
        li.hidden = !hit;
        if (hit) { shown++; }
      });
      sec.hidden = !!needle && shown === 0;
    });
  });
})();
"""


def local_tz(name):
    """The display timezone, never fatal.

    Windows ships no tz database, so `ZoneInfo("Asia/Ho_Chi_Minh")` raises there
    while the Linux container resolves it fine. Pulling in `tzdata` for one
    lookup would break the two-runtime-dependency rule, so an unresolvable name
    falls back to the host's own offset and says so once.

    ponytail: host offset as the fallback - if a zone with DST ever matters
    here, add `tzdata` to requirements.txt and drop the fallback.
    """
    try:
        return ZoneInfo(name)
    except Exception as exc:  # ZoneInfoNotFoundError, ValueError, TypeError
        fallback = dt.datetime.now().astimezone().tzinfo or dt.timezone.utc
        if name not in _WARNED:
            _WARNED.add(name)
            log.warning("timezone %r unavailable (%s), rendering in the host's "
                        "own offset %s", name, exc, fallback)
        return fallback


def day_bounds(now, tz):
    """The local day containing `now`, as a half-open UTC range.

    Storage is UTC and display is local; this is the one function that crosses
    between them, so "today" means one thing on the page and one thing in SQL.
    """
    start_local = now.astimezone(tz).replace(
        hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + dt.timedelta(days=1)
    utc = dt.timezone.utc
    return start_local.astimezone(utc), end_local.astimezone(utc)


def _e(text):
    return html.escape("" if text is None else str(text), quote=True)


def _when(moment, tz):
    """`<time>` for a story, or an honest dash when the source gave no date."""
    if moment is None:
        return '<time title="the source published no timestamp">--</time>'
    local = moment.astimezone(tz)
    return '<time datetime="{}">{}</time>'.format(
        _e(moment.isoformat()), _e(local.strftime("%H:%M %d/%m")))


def _story(row, hot, tz):
    return (
        '<li class="{cls}"><a href="{url}" rel="noopener noreferrer">{title}</a>'
        '<span class="meta"><span class="score">{score:.2f}</span> &middot; '
        '{sources} &middot; {when}</span></li>').format(
            cls="story hot" if hot else "story",
            url=_e(row.get("url") or row.get("canonical_url") or "#"),
            title=_e(row.get("title")),
            score=row.get("score") or 0.0,
            sources=_e(", ".join(row.get("sources") or ())) or "-",
            when=_when(row.get("published_at"), tz))


def _group(label, rows, threshold, tz):
    if not rows:
        body = '<p class="empty">no stories today</p>'
    else:
        body = '<ol class="stories">{}</ol>'.format("".join(
            _story(row, index < threshold, tz) for index, row in enumerate(rows)))
    return ('<section class="group"><h2>{label} <span class="n">{n}</span></h2>'
            '{body}</section>').format(label=_e(label), n=len(rows), body=body)


def _summary(text):
    """The AI summary as one `<p>` per topic, or nothing at all.

    The model was asked for `<topic> — <sentences>`, one line per topic, so the
    split is on the first em dash and the topic half is bolded. A line that
    carries no separator is rendered whole rather than dropped: a model that
    ignored the format still wrote a sentence, and a sentence the reader cannot
    see is worse than an unbolded one.

    Everything here came off somebody else's endpoint, answering every thirty
    minutes, so it goes through `_e` exactly like a feed title does. This is the
    same trust boundary, reached from a new direction.
    """
    if not (text or "").strip():
        return ""

    paragraphs = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        topic, sep, rest = line.partition("—")
        if sep and topic.strip() and rest.strip():
            paragraphs.append("<p><strong>{}</strong> — {}</p>".format(
                _e(topic.strip()), _e(rest.strip())))
        else:
            paragraphs.append("<p>{}</p>".format(_e(line)))

    if not paragraphs:
        return ""
    return '<section class="summary">{}</section>'.format("".join(paragraphs))


def _day_nav(data_dir, today):
    """Links to every snapshot on disk, newest first, today's included.

    Today's file is added explicitly rather than globbed: it is written by this
    same call, and scanning before writing it would leave the current day off
    its own page.
    """
    days = Path(data_dir) / DAYS_DIR
    stems = {p.stem for p in days.glob("*.html")} | {today}
    return '<nav class="days">{}</nav>'.format("".join(
        '<a href="{dir}/{d}.html"{cur}>{d}</a>'.format(
            dir=DAYS_DIR, d=_e(stem), cur=' aria-current="page"'
            if stem == today else "")
        for stem in sorted(stems, reverse=True)))


def _page(labels, day_rows, meta, tz, threshold, today, nav, summary=None):
    generated = meta.get("generated_at")
    generated_local = generated.astimezone(tz).strftime("%H:%M %d/%m/%Y") \
        if generated else "-"
    return (
        "<!doctype html>\n"
        '<html lang="vi" data-theme="">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>news-radar &middot; {today}</title>\n"
        "<style>{style}</style>\n</head>\n<body>\n"
        '<header><h1>news-radar <span class="day">{today}</span></h1>\n'
        '<div class="bar">'
        '<input id="q" type="search" placeholder="Filter today\'s stories"'
        ' autocomplete="off" spellcheck="false">'
        '<button id="theme" type="button">Theme</button></div>\n'
        "{nav}</header>\n<main>\n{summary}{groups}\n</main>\n"
        "<footer>{fetched} fetched &middot; {matched} matched &middot; "
        "{kept} kept today &middot; {sources} source(s), {errors} failed "
        "&middot; run {run} at {generated}</footer>\n"
        "<script>{script}</script>\n</body>\n</html>\n").format(
            today=_e(today),
            style=STYLE,
            nav=nav,
            summary=_summary(summary),
            groups="\n".join(
                _group(label, day_rows.get(label) or [], threshold, tz)
                for label in labels),
            fetched=_e(meta.get("fetched", 0)),
            matched=_e(meta.get("matched", 0)),
            kept=sum(len(day_rows.get(label) or []) for label in labels),
            sources=_e(meta.get("sources", 0)),
            errors=_e(meta.get("errors", 0)),
            run=_e(meta.get("run_id", "-")),
            generated=_e(generated_local),
            script=SCRIPT)


def write(data_dir, labels, day_rows, meta, tz, threshold=5, summary=None):
    """Write `index.html` and today's snapshot. Returns the paths written.

    `labels` fixes the group order and is what keeps an empty group on the page:
    a keyword that has gone quiet looks identical to a keyword nobody wrote
    about, and only one of those is worth knowing.

    The snapshot is rewritten every run rather than once at midnight. A past day
    is still never touched, because the filename moves with the date - and there
    is no rollover branch to get wrong.

    `summary` is the AI summary, one topic per line, or `None`. Absent is the
    shipped case - `ai.enabled` defaults to false - and it renders nothing at
    all rather than an empty card, so a clone's page is the page it always was.
    """
    data_dir = Path(data_dir)
    (data_dir / DAYS_DIR).mkdir(parents=True, exist_ok=True)

    generated = meta.get("generated_at") or dt.datetime.now(dt.timezone.utc)
    today = generated.astimezone(tz).date().isoformat()

    page = _page(labels, day_rows, meta, tz, threshold, today,
                 _day_nav(data_dir, today), summary)

    written = []
    for path in (data_dir / INDEX_NAME,
                 data_dir / DAYS_DIR / "{}.html".format(today)):
        path.write_text(page, encoding="utf-8")
        written.append(path)

    log.info("rendered %s (%d group(s), %d story(ies))", written[0], len(labels),
             sum(len(day_rows.get(label) or []) for label in labels))
    return written
