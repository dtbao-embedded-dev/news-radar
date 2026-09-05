---
title: Crawl CLI - python -m news_radar
category: interface
purpose: The command-line contract of the crawl service itself, its flags, its exit codes, and how it behaves as a container process.
status: active
updated: 2026-09-05
source: src/news_radar/__main__.py, src/news_radar/config.py, src/news_radar/fetch/, src/news_radar/store.py, src/news_radar/render.py, Dockerfile
confidence: confirmed
keywords: python -m news_radar, --once, --config, --debug, entrypoint, schedule loop, SIGTERM, exit codes, crawl
order: 4
---

# Crawl CLI - `python -m news_radar`

> The application entrypoint and the image's `ENTRYPOINT`. It owns the schedule
> loop and nothing else; every stage it calls lives in its own module.

```
python -m news_radar [--once] [--config PATH] [--debug]
```

| Flag | Effect |
|------|--------|
| *(none)* | Loop forever on `schedule.interval_minutes`, crawling immediately unless `schedule.run_on_start` is `false` |
| `--once` | One cycle, then exit. This is the command a phase is verified with - P1 is done when it prints N raw items |
| `--config PATH` | Config file to read. Default: `$NEWS_RADAR_CONFIG`, then `config/config.yaml` |
| `--debug` | `DEBUG` logging. `advanced.debug: true` in the config does the same |

| Exit code | Meaning |
|-----------|---------|
| `0` | The cycle ran, or the loop was stopped by a signal |
| `1` | The configuration is unusable; every problem is listed, and nothing was started |

## Behaviour that matters

**Config problems are reported together and are fatal.** `config.load()` collects
every problem and raises once, so an operator fixes them in one pass instead of
one per restart. There is no fallback to an all-default config: a radar that
hunts nothing and reports to nobody looks like success. See [[config-and-env]].

**The sleep is interruptible.** The loop waits on a `threading.Event` rather than
`time.sleep`, and `SIGTERM`/`SIGINT` set it. `docker stop` allows 10 seconds
before `SIGKILL`; a plain sleep of `interval_minutes` would be killed every time.
Measured: `docker stop` returns in under a second mid-interval.

**One bad cycle does not end the service.** `crawl()` is called inside a
`try/except`; a traceback is logged and the next cycle runs. Letting it escape
would exit the process, and `restart: unless-stopped` would restart straight back
into the same failure, losing the schedule.

**Logging goes to stdout, unbuffered.** The image sets `PYTHONUNBUFFERED=1`; a
service that logs once every 30 minutes would otherwise sit in a block buffer and
look hung under `docker logs`.

## What one cycle does today

`crawl()` builds one `Fetcher` (the per-host throttle state lives on it), parses
the keyword file, reads every enabled fixed feed, then every enabled search
template crossed with every keyword group, matches what came back against the
groups, collapses duplicates, ranks and caps each group - and then **stores and
publishes it**. See [[fetch-layer]], [[selection-layer]] and [[storage-layer]]
for the signatures at each step.

It prints **one count line per configured source, zeros included** - a source
that quietly stops returning items looks exactly like a quiet week in a total.
Then the summary, the errors, the shortlist group by group, and what was
written:

```
INFO  fixed feeds: 208 item(s) from 8 source(s)
INFO    hn                   20 item(s)
INFO    r_embedded            0 item(s)  [failed]
INFO  search feeds: 156 item(s) from 7 group(s) x 2 template(s)
INFO    google_news          16 item(s)
WARN  source failed: r_embedded - URLError: ...
INFO  fetched 364 raw item(s) in 49.9s, 1 source(s) failed
INFO  matched 68 item(s) -> 61 story(ies) after dedup -> 43 kept across 7 group(s)
INFO    ESP32 - 10 item(s)
INFO      0.42  I Connected My Withings Body+ to Home Assistant with an ESP32  [hn_algolia]
INFO    Security - 0 item(s)
INFO  rendered output/index.html (7 group(s), 90 story(ies))
INFO  stored 43 match row(s) as run 20260905T081328Z; the page shows 90
      story(ies) across 7 group(s) today
INFO  notifying 2 channel(s) in incremental mode
INFO    telegram 2 message(s), 43 story(ies)
INFO    discord  5 message(s), 43 story(ies)
```

The next cycle over the same news says so instead:

```
INFO  notifying 2 channel(s) in incremental mode
INFO    telegram nothing new to send
INFO    discord  nothing new to send
```

**Every group is reported, empty ones included.** `Security - 0 item(s)` is a
line in the run, not a missing section: a keyword that has gone quiet is exactly
what a total would hide, and the page makes the same promise for the same reason.

**The page shows more stories than the run kept.** `43 kept` is this cycle's
shortlist; `90 story(ies) today` is what the store holds for the whole local day.
The page is rendered from the store, never from the run in memory - that is what
makes a restart at noon still publish what the morning found.

**An unusable keyword file costs the search feeds, not the run.** The fixed
feeds do not need it, so `crawl()` logs the `KeywordError` on one line and
continues with no groups. Losing half a cycle beats losing all of it. With no
groups there is also no order to render in, so the page is **left as it was**
rather than rewritten with no sections - a blank page reads as "no news" instead
of "the radar is broken".

**Storage and rendering cannot cost the fetch.** `_publish()` is wrapped whole: a
locked database, a full disk or a read-only volume is logged with its traceback
and the cycle still returns the shortlist it spent fifty seconds collecting. It
returns the `run_id`, so a cycle whose storage failed notifies nothing rather
than notifying a run that was never written.

**Only new stories are pushed, and a quiet cycle is silent.** The run is read
back out of the store and diffed against the per-channel seen-set; a story is
recorded as sent only after the message carrying it was accepted. Two Telegram
messages and five Discord ones for the same 43 stories is the 4000/1900 limit,
not a bug. See [[notify-channels]].

**A failing channel costs neither the page nor the other channel.** `_notify()`
is guarded whole *and* once per channel, so a revoked webhook leaves Telegram
still attempted.

## What it does not do yet

Nothing here. P5 was deployment - the Cloudflare Tunnel connector and the first
unattended live run - and it changed neither the flags nor the exit codes above;
P6 is ops, and is not expected to either.
