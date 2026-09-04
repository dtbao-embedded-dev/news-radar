# news-radar

A self-hosted news radar: it hunts stories on a schedule, filters them against
your own keyword file, publishes them to <https://news.dtbao.org>, and pushes
only the new matches to Telegram and Discord.

Two ways of hunting feed one filter. **Fixed feeds** - Hacker News, Lobsters,
Hackaday, LWN, r/embedded, VnExpress So hoa, GenK, Tinh te - are fetched whole
and filtered locally. **Search feeds** are built at runtime from each keyword
group, so the keyword travels into the URL (Google News RSS, HN Algolia, Reddit
search) and the source does the first cut. Adding a keyword adds a hunting path;
no code changes.

## Status

**P0 Foundation.** The design is complete and the tooling works; the application
layer is specified but not written yet. What runs today: `scripts/setup.py`,
`scripts/release.py`, the release CI, and the Caddy half of the docker stack.
See `docs/memory-ai/progress.md` for exactly what works and what is left.

## Quick start

```bash
git clone git@github.com:dtbao-embedded-dev/news-radar.git
cd news-radar
python scripts/setup.py
docker compose -f docker/docker-compose.yml up -d
```

Same three steps on Windows and Linux. `setup.py` checks Python and Docker,
creates `config/config.yaml` and `docker/.env` from their templates, and asks for
the Telegram and Discord secrets. Run it with `--dry-run` first to see what it
would do. Full procedure: `docs/memory-ai/rule/setup-homelab.md`.

## Configuring what it hunts

- `config/config.yaml` - feeds, search templates, schedule, ranking weights.
- `config/frequency_words.txt` - the keyword groups. A blank line separates
  groups; `+` requires a word, `!` excludes one, `@n` caps a group, `/re/`
  matches by regex.

Every key is documented in `docs/memory-ai/interface/config-and-env.md`.

## Releasing

```bash
python scripts/release.py 0.2.0 --dry-run   # see the plan
python scripts/release.py 0.2.0             # cut it
```

Writes the changelog, commits `chore(release): v0.2.0` on `release/*`, merges
into `developing` then `main`, tags, returns, and pushes. CI turns the tag into a
GitHub Release. Full rules: `docs/memory-ai/rule/release-flow.md`.

## Documentation

Everything lives in `docs/memory-ai/`. Read `memory.md` for the whole design in
one pass, or `overview.md` to find a single topic. Start with `progress.md` and
`active-context.md` to see where the work is right now.

## Prior art

[TrendRadar](https://github.com/sansan0/TrendRadar) solves the same shape of
problem and is worth reading. news-radar is written from scratch and shares no
code with it - see `docs/memory-ai/adr/adr-0001-clean-room-from-trendradar.md`.
