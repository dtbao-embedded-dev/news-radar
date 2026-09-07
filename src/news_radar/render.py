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

__all__ = ["local_tz", "day_bounds", "write", "remove", "DAYS_DIR"]

log = logging.getLogger("news_radar.render")

DAYS_DIR = "days"
INDEX_NAME = "index.html"

# Zone names already reported as unresolvable. Without it the fallback below
# logs the same line every thirty minutes forever.
_WARNED = set()

STYLE = """
*, *::before, *::after { box-sizing: border-box; }
/* Not cosmetic: `li.story` is a grid, and an author `display` beats the
   browser's own `[hidden] { display: none }`. Without this line the search box
   filters nothing. */
[hidden] { display: none !important; }
html { -webkit-text-size-adjust: 100%; scroll-behavior: smooth; }
body { margin: 0; }
.wrap { width: 80%; margin: 0 auto; }
@media (max-width: 900px) { .wrap { width: 92%; } }
a:focus-visible, button:focus-visible, input:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px;
}
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; scroll-behavior: auto !important; }
}
:root {
  color-scheme: light;
  --bg:#ffffff; --panel:#f7f8fa; --ink:#101418; --ink2:#39414a; --dim:#6e7883;
  --line:#e6e9ed; --hot:#b91c1c; --accent:#0f766e;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg:#101418; --panel:#161b21; --ink:#eef2f6; --ink2:#c2cad3; --dim:#828d99;
    --line:#232a32; --hot:#f87171; --accent:#5eead4;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg:#101418; --panel:#161b21; --ink:#eef2f6; --ink2:#c2cad3; --dim:#828d99;
  --line:#232a32; --hot:#f87171; --accent:#5eead4;
}
body { background:var(--bg); color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased; }
.shell { display:grid; grid-template-columns:16rem minmax(0,1fr); gap:2.5rem;
         padding:1.6rem 0 2.5rem; align-items:start; }
@media (max-width:900px) { .shell { grid-template-columns:1fr; gap:1.2rem; } }
aside { position:sticky; top:1.2rem; }
@media (max-width:900px) { aside { position:static; } }
h1 { margin:0 0 .2rem; font-size:1.2rem; font-weight:650;
     letter-spacing:-.015em; }
h1::before { content:""; display:inline-block; width:.5rem; height:.5rem;
             border-radius:50%; background:var(--accent); margin-right:.45rem;
             vertical-align:.08em; }
.day { color:var(--dim); font-size:.8rem; }
.stat { margin:.9rem 0 0; padding:.65rem .75rem; background:var(--panel);
        border:1px solid var(--line); border-radius:.5rem; color:var(--dim);
        font-size:.76rem; line-height:1.9; font-variant-numeric:tabular-nums; }
.stat span { display:flex; }
.stat b { margin-left:auto; color:var(--ink2); font-weight:600; }
.stat b.bad { color:var(--hot); }
.rail-bar { display:flex; gap:.4rem; margin:.9rem 0 .8rem; }
#q { flex:1; min-width:0; padding:.45rem .65rem; border:1px solid var(--line);
     border-radius:.45rem; background:var(--panel); color:inherit;
     font:inherit; font-size:.88rem; }
#q::placeholder { color:var(--dim); }
#theme { padding:.45rem .6rem; border:1px solid var(--line);
         border-radius:.45rem; background:var(--panel); color:var(--ink2);
         font:inherit; font-size:.82rem; cursor:pointer; }
nav.jump { display:flex; flex-direction:column; gap:.05rem; }
nav.jump a { display:flex; align-items:center; gap:.5rem; padding:.3rem .55rem;
             border-radius:.4rem; color:var(--ink2); text-decoration:none;
             font-size:.85rem; }
nav.jump a:hover { background:var(--panel); color:var(--ink); }
nav.jump a .n { margin-left:auto; color:var(--dim); font-size:.75rem;
                font-variant-numeric:tabular-nums; }
nav.jump a .n.zero { opacity:.45; }
nav.days { display:flex; flex-wrap:wrap; gap:.3rem; margin-top:1rem;
           padding-top:.8rem; border-top:1px solid var(--line);
           font-size:.75rem; }
nav.days a { padding:.1rem .4rem; border-radius:.3rem; color:var(--dim);
             text-decoration:none; }
nav.days a:hover { background:var(--panel); color:var(--ink); }
nav.days a[aria-current="page"] { color:var(--accent); font-weight:600; }
section.group { margin:0 0 2.2rem; scroll-margin-top:1.5rem; }
section.group h2 { display:flex; align-items:baseline; gap:.55rem;
                   margin:0 0 .6rem; padding:0 .6rem .45rem;
                   border-bottom:1px solid var(--line);
                   font-size:.78rem; font-weight:650; letter-spacing:.08em;
                   text-transform:uppercase; color:var(--ink2); }
section.group h2 .n { color:var(--dim); font-weight:400;
                      font-size:.75rem; font-variant-numeric:tabular-nums; }
ol.stories { list-style:none; margin:0; padding:0; }
/* Two cells on one baseline: the title takes what it needs, the time is
   pinned to the right edge of the column. `auto` rather than a fixed width
   because "--" is what an undated story renders. */
li.story { display:grid; grid-template-columns:minmax(0,1fr) auto;
           column-gap:1.5rem; align-items:baseline;
           padding:.45rem .6rem; border-radius:.4rem; }
/* The AI sentence, under the headline and spanning both columns so it wraps
   against the full width instead of the title's. Absent for a story nothing
   was written about, which is the shipped case with `ai.enabled` false. */
li.story p.gist { grid-column:1 / -1; margin:.2rem 0 0; padding-right:1.5rem;
                  color:var(--ink2); font-size:.82rem; line-height:1.45; }
li.story:hover { background:var(--panel); }
li.story a { color:var(--ink); text-decoration:none; font-weight:500;
             line-height:1.4; }
/* All that is left of the top-of-group mark: no rule, no colour, no number.
   The order of the list is the ranking now. */
li.story.hot a { font-weight:650; }
li.story a:hover { color:var(--accent); text-decoration:underline;
                   text-underline-offset:2px; }
li.story .meta { color:var(--dim); font-size:.75rem; white-space:nowrap;
                 font-variant-numeric:tabular-nums; }
p.empty { color:var(--dim); font-style:italic; margin:0; padding:.2rem .6rem;
          font-size:.88rem; }
footer { color:var(--dim); font-size:.76rem; padding:1rem 0 2.5rem;
         border-top:1px solid var(--line); }
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


def _slug(label):
    """A fragment id for a group, so the rail can link to its section.

    Non-ASCII survives: a Vietnamese label makes a Vietnamese id, which is a
    valid HTML id and a fragment the browser percent-encodes on its own.
    """
    return "g-" + "".join(c if c.isalnum() else "-" for c in label.lower())


def _story(row, hot, tz):
    """Title on the left, timestamp on the right, the AI sentence underneath.

    Neither the score nor the source ids reach the page. Both are still in the
    store - `matches.score` is what put this row above the next one, and
    `item_sources` still records who carried it - but a reader asked what
    `0.74` meant, and a number nobody can act on is chrome. `hot` survives as
    a heavier title: the order of the list is the ranking.

    `target="_blank"` because a story leads off this site and the report is what
    the reader came back to; the `rel` beside it is the half that stops the
    opened page reaching back through `window.opener`. Only story links get it -
    the group and day navs move around this same report and belong in this tab.

    `ai_summary` came off somebody else's endpoint, answering every thirty
    minutes, so it goes through `_e` exactly like a feed title does. Same trust
    boundary, reached from a new direction. Empty renders no element at all
    rather than an empty paragraph: that is the shipped case, and a column of
    blank gaps under every headline is worse than the page that had none.
    """
    gist = (row.get("ai_summary") or "").strip()
    return (
        '<li class="{cls}"><a href="{url}" target="_blank"'
        ' rel="noopener noreferrer">{title}</a>'
        '<span class="meta">{when}</span>{gist}</li>').format(
            cls="story hot" if hot else "story",
            url=_e(row.get("url") or row.get("canonical_url") or "#"),
            title=_e(row.get("title")),
            when=_when(row.get("published_at"), tz),
            gist='<p class="gist">{}</p>'.format(_e(gist)) if gist else "")


def _group(label, rows, threshold, tz):
    if not rows:
        body = '<p class="empty">no stories today</p>'
    else:
        body = '<ol class="stories">{}</ol>'.format("".join(
            _story(row, index < threshold, tz) for index, row in enumerate(rows)))
    return ('<section class="group" id="{id}">'
            '<h2>{label} <span class="n">{n}</span></h2>'
            '{body}</section>').format(id=_e(_slug(label)), label=_e(label),
                                       n=len(rows), body=body)


def _jump_nav(labels, day_rows):
    """The rail's group list: every label, its count, in page order.

    A group with nothing in it is dimmed rather than dropped, for the same
    reason its section stays on the page - a keyword that has gone quiet looks
    identical to a keyword nobody wrote about, and only one of those is worth
    knowing.
    """
    return '<nav class="jump">{}</nav>'.format("".join(
        '<a href="#{id}">{label}<span class="n{zero}">{n}</span></a>'.format(
            id=_e(_slug(label)), label=_e(label), n=count,
            zero=" zero" if not count else "")
        for label, count in ((l, len(day_rows.get(l) or [])) for l in labels)))


def _day_nav(data_dir, today, prefix=""):
    """Links to every snapshot on disk, newest first, today's included.

    Today's file is added explicitly rather than globbed: it is written by this
    same call, and scanning before writing it would leave the current day off
    its own page.

    `prefix` is whatever stands between the page carrying this nav and the
    `days/` directory - `"days/"` for `index.html` at the root, `""` for a
    snapshot that already lives in there. It is not cosmetic: a relative href
    is resolved against the file carrying it, so the same string on both pages
    sends the day page to `/days/days/<date>.html`, which is a 404.
    """
    days = Path(data_dir) / DAYS_DIR
    stems = {p.stem for p in days.glob("*.html")} | {today}
    return '<nav class="days">{}</nav>'.format("".join(
        '<a href="{prefix}{d}.html"{cur}>{d}</a>'.format(
            prefix=prefix, d=_e(stem), cur=' aria-current="page"'
            if stem == today else "")
        for stem in sorted(stems, reverse=True)))


def _page(labels, day_rows, meta, tz, threshold, today, nav):
    """The whole document: a sticky rail of context, a column of stories.

    The rail carries what used to be spread across a header and a footer - the
    run's own numbers, the filter, the group list, the day list - so it stays
    on screen while the stories scroll. Below 900px it stops sticking and
    becomes the top of the page.
    """
    generated = meta.get("generated_at")
    generated_local = generated.astimezone(tz).strftime("%H:%M %d/%m/%Y") \
        if generated else "-"
    errors = meta.get("errors", 0)
    return (
        "<!doctype html>\n"
        '<html lang="vi" data-theme="">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>News Radar &middot; {today}</title>\n"
        "<style>{style}</style>\n</head>\n<body>\n"
        '<div class="shell wrap">\n'
        '<aside>\n<h1>News Radar</h1>'
        '<div class="day">{today}</div>\n'
        '<div class="stat">'
        "<span>kept today <b>{kept}</b></span>"
        "<span>matched <b>{matched}</b></span>"
        "<span>fetched <b>{fetched}</b></span>"
        "<span>sources <b>{sources}</b></span>"
        "<span>failed <b{bad}>{errors}</b></span></div>\n"
        '<div class="rail-bar">'
        '<input id="q" type="search" placeholder="Filter today\'s stories"'
        ' autocomplete="off" spellcheck="false">'
        '<button id="theme" type="button" title="Toggle theme"'
        ' aria-label="Toggle theme">&#9680;</button></div>\n'
        "{jump}\n{nav}\n</aside>\n"
        "<main>\n{groups}\n"
        "<footer>run {run} at {generated}</footer>\n</main>\n</div>\n"
        "<script>{script}</script>\n</body>\n</html>\n").format(
            today=_e(today),
            style=STYLE,
            jump=_jump_nav(labels, day_rows),
            nav=nav,
            groups="\n".join(
                _group(label, day_rows.get(label) or [], threshold, tz)
                for label in labels),
            fetched=_e(meta.get("fetched", 0)),
            matched=_e(meta.get("matched", 0)),
            kept=sum(len(day_rows.get(label) or []) for label in labels),
            sources=_e(meta.get("sources", 0)),
            # Red is for a failure that happened, not for the word "failed".
            bad=' class="bad"' if errors else "",
            errors=_e(errors),
            run=_e(meta.get("run_id", "-")),
            generated=_e(generated_local),
            script=SCRIPT)


def write(data_dir, labels, day_rows, meta, tz, threshold=5):
    """Write `index.html` and today's snapshot. Returns the paths written.

    `labels` fixes the group order and is what keeps an empty group on the page:
    a keyword that has gone quiet looks identical to a keyword nobody wrote
    about, and only one of those is worth knowing.

    The snapshot is rewritten every run rather than once at midnight. A past day
    is still never touched, because the filename moves with the date - and there
    is no rollover branch to get wrong.

    The two files carry the same page and two different day lists: they sit at
    different depths, and a relative href is resolved against the file carrying
    it. One nav for both is how `days/<date>.html` inside `days/` became
    `/days/days/<date>.html` and a 404.

    The AI summaries are not an argument: they ride in the rows themselves,
    under `ai_summary`, written into the store before this is called. Absent is
    the shipped case - `ai.enabled` defaults to false - and a row without one
    renders exactly the page this project had before.
    """
    data_dir = Path(data_dir)
    (data_dir / DAYS_DIR).mkdir(parents=True, exist_ok=True)

    generated = meta.get("generated_at") or dt.datetime.now(dt.timezone.utc)
    today = generated.astimezone(tz).date().isoformat()

    written = []
    for path, prefix in ((data_dir / INDEX_NAME, DAYS_DIR + "/"),
                         (data_dir / DAYS_DIR / "{}.html".format(today), "")):
        page = _page(labels, day_rows, meta, tz, threshold, today,
                     _day_nav(data_dir, today, prefix))
        path.write_text(page, encoding="utf-8")
        written.append(path)

    log.info("rendered %s (%d group(s), %d story(ies))", written[0], len(labels),
             sum(len(day_rows.get(label) or []) for label in labels))
    return written


def remove(data_dir):
    """Delete the published page. Returns the paths removed, newest name last.

    The other half of `report.html`. Not writing the page would leave the last
    one it wrote sitting on the web server forever, dated and wrong - a reader
    cannot tell a frozen report from a working one, and that is the exact
    failure the switch was turned off to avoid.

    Three things it deliberately does not do:

    - **It never touches anything but a page.** `news.db` lives in this same
      directory, and it holds every story the radar has ever seen. Only
      `index.html` and `days/*.html` - the two names this module writes - are
      ever unlinked.
    - **It leaves a `days/` that still has something in it.** The directory is
      removed only when it is empty, so a file somebody else put there keeps
      both itself and its directory.
    - **It says nothing when there was nothing to remove.** With the report
      off this runs every cycle, and a line every ten minutes about a
      directory that has been clean since Tuesday is how a log stops being
      read.
    """
    data_dir = Path(data_dir)
    removed = []

    for path in [data_dir / INDEX_NAME] + sorted(
            (data_dir / DAYS_DIR).glob("*.html")):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed.append(path)

    try:
        (data_dir / DAYS_DIR).rmdir()
    except OSError:
        # Missing, or not empty. Both are fine and neither is this function's
        # business to force.
        pass

    if removed:
        log.info("the HTML report is off: removed %d published file(s) from %s",
                 len(removed), data_dir)
    return removed
