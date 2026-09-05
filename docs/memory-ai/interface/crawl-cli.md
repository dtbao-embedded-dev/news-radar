---
title: Crawl CLI - python -m news_radar
category: interface
purpose: The command-line contract of the crawl service itself, its flags, its exit codes, and how it behaves as a container process.
status: active
updated: 2026-09-05
source: src/news_radar/__main__.py, src/news_radar/config.py, Dockerfile
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

## What it does not do yet

`crawl()` is a placeholder. It logs how many feeds and search templates are
enabled and which channels would be notified, then logs
`fetch is not implemented yet (P1) - 0 items this cycle` and returns `0`. It
returns a count rather than pretending: a loop that reports success while doing
nothing is worse than one that says it is empty.

P1 replaces the body with the fetch layer, P2 the selection, P3 the store and the
page, P4 the senders. The flags and exit codes above do not change with them.
