#!/usr/bin/env python3
"""Checks for src/news_radar/config.py - plain asserts, no test framework.

    python tests/test_config.py

Needs PyYAML, which config.py imports. Writes its fixtures to a temp directory
and never reads the repository's own config/config.yaml.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from news_radar import config as cfgmod  # noqa: E402

FAILURES = []
TMP = pathlib.Path(tempfile.mkdtemp(prefix="news-radar-config-"))
COUNTER = [0]


def check(name, condition, detail=""):
    if not condition:
        FAILURES.append("{}{}".format(name, ": " + detail if detail else ""))


def check_raises(name, fn, *args, **kwargs):
    """Assert ConfigError, and hand the message back for further checking."""
    try:
        fn(*args, **kwargs)
    except cfgmod.ConfigError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append("{}: raised {!r}, expected ConfigError".format(name, exc))
        return ""
    FAILURES.append("{}: did not raise ConfigError".format(name))
    return ""


def write(text):
    COUNTER[0] += 1
    path = TMP / "config-{}.yaml".format(COUNTER[0])
    path.write_text(text, encoding="utf-8")
    return path


SECRETS = {
    "TELEGRAM_BOT_TOKEN": "t",
    "TELEGRAM_CHAT_ID": "-1",
    "DISCORD_WEBHOOK_URL": "https://example.invalid/w",
}

MINIMAL = """
feeds:
  - id: hn
    name: Hacker News
    url: https://hnrss.org/frontpage
"""


# --------------------------------------------------------------------------
# defaults and merging
# --------------------------------------------------------------------------

cfg = cfgmod.load(write(MINIMAL), env=SECRETS)

check("a key absent from the file takes the documented default",
      cfg.get("schedule.interval_minutes") == 30)
check("a nested default survives when a sibling is overridden",
      cfg.get("rank.weight_freshness") == 0.2)
check("dotted lookup of a missing key returns the fallback",
      cfg.get("nope.not.here", "fallback") == "fallback")
check("the file's own value wins over the default",
      cfg.get("feeds")[0]["id"] == "hn")
check("a feed with no explicit enabled counts as enabled",
      len(cfg.enabled_feeds()) == 1)
check("the config path is remembered", cfg.path is not None)

partial = cfgmod.load(write(MINIMAL + "\nschedule:\n  interval_minutes: 5\n"), env=SECRETS)
check("overriding one key of a section keeps its siblings",
      partial.get("schedule.interval_minutes") == 5
      and partial.get("schedule.run_on_start") is True,
      "got {!r}".format(partial.get("schedule")))

check("{version} is substituted into the user agent",
      "{version}" not in cfg.user_agent() and cfg.user_agent().startswith("news-radar/"),
      "got {!r}".format(cfg.user_agent()))

# A list is replaced, never merged - half a feed list from two sources would be
# impossible to reason about.
two = cfgmod.load(write("""
feeds:
  - id: a
    url: https://a.invalid/rss
  - id: b
    url: https://b.invalid/rss
"""), env=SECRETS)
check("a list in the file replaces the default list wholesale",
      [f["id"] for f in two.get("feeds")] == ["a", "b"])

disabled = cfgmod.load(write("""
feeds:
  - id: keep
    url: https://a.invalid/rss
  - id: skip
    url: https://b.invalid/rss
    enabled: false
"""), env=SECRETS)
check("enabled: false is skipped without deleting the entry",
      [f["id"] for f in disabled.enabled_feeds()] == ["keep"]
      and len(disabled.get("feeds")) == 2)

# PyYAML is YAML 1.1: bare on/off/yes/no parse as booleans, and the id is what
# every source lookup and the seen-set are keyed on. Found by this test file
# using `id: on` as a fixture and getting True back.
msg = check_raises("a bare on/off id is refused, not silently made a bool",
                   cfgmod.load, write("""
feeds:
  - id: off
    url: https://a.invalid/rss
"""), env=SECRETS)
check("the message says the id must be a string", "must be a non-empty string" in msg, msg)
check("the message explains the YAML booleans", "quote them" in msg, msg)

quoted = cfgmod.load(write("""
feeds:
  - id: "off"
    url: https://a.invalid/rss
"""), env=SECRETS)
check("quoting the same id makes it legal again",
      [f["id"] for f in quoted.enabled_feeds()] == ["off"])

msg = check_raises("a feed with no url is refused", cfgmod.load, write("""
feeds:
  - id: nourl
"""), env=SECRETS)
check("the missing-url message names the feed", "nourl" in msg, msg)


# --------------------------------------------------------------------------
# the secret rule - the one this project cares most about
# --------------------------------------------------------------------------

msg = check_raises("an enabled channel with no token is fatal",
                   cfgmod.load, write(MINIMAL), env={})
check("the message names the missing variable", "TELEGRAM_BOT_TOKEN" in msg, msg)
check("the message names the channel", "telegram" in msg, msg)
check("every missing variable is reported at once, not one per run",
      msg.count("is not set") >= 3, msg)

msg = check_raises("a blank token counts as missing, not as set",
                   cfgmod.load, write(MINIMAL),
                   env=dict(SECRETS, TELEGRAM_BOT_TOKEN="   "))
check("whitespace does not satisfy a required secret",
      "TELEGRAM_BOT_TOKEN" in msg, msg)

off = cfgmod.load(write(MINIMAL + """
notification:
  channels:
    telegram:
      enabled: false
    discord:
      enabled: false
"""), env={})
check("disabling both channels needs no secrets at all",
      off.enabled_channels() == [])

master_off = cfgmod.load(write(MINIMAL + "\nnotification:\n  enabled: false\n"), env={})
check("the master switch overrides per-channel enabled",
      master_off.enabled_channels() == [])


# --------------------------------------------------------------------------
# the rest of validation
# --------------------------------------------------------------------------

msg = check_raises("a zero interval is refused", cfgmod.load,
                   write(MINIMAL + "\nschedule:\n  interval_minutes: 0\n"), env=SECRETS)
check("the interval message says what is wrong", "interval_minutes" in msg, msg)

msg = check_raises("a bool is not an integer interval", cfgmod.load,
                   write(MINIMAL + "\nschedule:\n  interval_minutes: true\n"), env=SECRETS)
check("True does not sneak through as 1", "interval_minutes" in msg, msg)

msg = check_raises("an unknown report mode is refused", cfgmod.load,
                   write(MINIMAL + "\nreport:\n  mode: whenever\n"), env=SECRETS)
check("the mode message lists the valid modes", "incremental" in msg, msg)

msg = check_raises("a search template without {kw} is refused", cfgmod.load, write("""
feeds:
  - id: hn
    url: https://hnrss.org/frontpage
search_templates:
  - id: broken
    url: https://example.invalid/search?q=fixed
"""), env=SECRETS)
check("the template message names the offender", "broken" in msg, msg)

msg = check_raises("hunting nothing is refused", cfgmod.load, write("""
feeds:
  - id: only
    url: https://a.invalid/rss
    enabled: false
"""), env=SECRETS)
check("the empty-source message says so", "nothing to hunt" in msg, msg)

msg = check_raises("a missing file is fatal, not an all-default config",
                   cfgmod.load, TMP / "does-not-exist.yaml", env=SECRETS)
check("the missing-file message points at setup.py", "setup.py" in msg, msg)

msg = check_raises("a non-mapping top level is refused", cfgmod.load,
                   write("- just\n- a\n- list\n"), env=SECRETS)
check("the shape message says mapping", "mapping" in msg, msg)

msg = check_raises("broken YAML is reported as broken YAML", cfgmod.load,
                   write("feeds: [unclosed\n"), env=SECRETS)
check("the YAML message says YAML", "YAML" in msg, msg)


# --------------------------------------------------------------------------
# the ops section - P6
# --------------------------------------------------------------------------

check("the heartbeat ships off, so a fresh clone pings nobody",
      cfg.get("ops.heartbeat_url") == "", repr(cfg.get("ops.heartbeat_url")))
check("the site check ships off too", cfg.get("ops.site_url") == "",
      repr(cfg.get("ops.site_url")))
check("backups default to a directory outside the served output/",
      cfg.get("ops.backup_dir") == "backups", repr(cfg.get("ops.backup_dir")))
check("a week of backups is the default", cfg.get("ops.backup_keep") == 7,
      repr(cfg.get("ops.backup_keep")))

msg = check_raises("a negative backup_keep is refused", cfgmod.load,
                   write(MINIMAL + "\nops:\n  backup_keep: -1\n"), env=SECRETS)
check("the backup_keep message names the key", "backup_keep" in msg, msg)

msg = check_raises("a bool is not a backup count", cfgmod.load,
                   write(MINIMAL + "\nops:\n  backup_keep: true\n"), env=SECRETS)
check("True does not sneak through as 1 here either",
      "backup_keep" in msg, msg)

# A typo'd heartbeat url is the failure this whole section exists to catch: it
# would be silently unpingable, which is exactly the silent failure P6-1 is for.
msg = check_raises("a non-http heartbeat url is refused", cfgmod.load,
                   write(MINIMAL + "\nops:\n  heartbeat_url: ftp://hc.invalid/x\n"),
                   env=SECRETS)
check("the heartbeat message names the key", "heartbeat_url" in msg, msg)

msg = check_raises("a site_url that is not a url is refused", cfgmod.load,
                   write(MINIMAL + "\nops:\n  site_url: news.dtbao.org\n"),
                   env=SECRETS)
check("the site_url message names the key", "site_url" in msg, msg)

ops_on = cfgmod.load(write(MINIMAL + """
ops:
  heartbeat_url: https://hc.invalid/ping/abc
  site_url: https://news.invalid/
  backup_keep: 0
"""), env=SECRETS)
check("a real https heartbeat url is accepted",
      ops_on.get("ops.heartbeat_url") == "https://hc.invalid/ping/abc")
check("backup_keep 0 is legal - it means back nothing up",
      ops_on.get("ops.backup_keep") == 0)
check("setting one ops key keeps the siblings",
      ops_on.get("ops.backup_dir") == "backups")


# --------------------------------------------------------------------------
# the ai section - P6-4
# --------------------------------------------------------------------------

# The whole section ships inert. P6-4 was dropped once for costing an API key
# and a bill, and the answer to that is not "it is cheap" - it is that an
# existing config.yaml that says nothing about `ai` must upgrade into this
# version and behave exactly as it did before.
check("the summary ships off", cfg.get("ai.enabled") is False,
      repr(cfg.get("ai.enabled")))
check("the default endpoint is OpenAI's own",
      cfg.get("ai.api_url") == "https://api.openai.com/v1/chat/completions",
      repr(cfg.get("ai.api_url")))
check("the default model is the cheap one",
      cfg.get("ai.model") == "gpt-4o-mini", repr(cfg.get("ai.model")))
check("five stories a topic is the default",
      cfg.get("ai.max_per_topic") == 5, repr(cfg.get("ai.max_per_topic")))
check("a completion gets longer than a feed does",
      cfg.get("ai.timeout_s") == 60, repr(cfg.get("ai.timeout_s")))
check("the daily message defaults to the morning",
      cfg.get("ai.notify_at_hour") == 8, repr(cfg.get("ai.notify_at_hour")))
check("an absent ai section costs an existing config nothing",
      cfgmod.load(write(MINIMAL), env=SECRETS).get("ai.enabled") is False)

# A key is deliberately NOT required, unlike a notification channel's token. A
# channel genuinely cannot work without its secret; an endpoint on the LAN
# answers perfectly well without one, and refusing to start would be this file
# telling the operator their own server does not exist. A *remote* endpoint with
# no key answers 401, which `summarize()` logs every cycle - visible, not silent.
no_key = cfgmod.load(write(MINIMAL + """
ai:
  enabled: true
  api_url: http://sglang.invalid:30000/v1/chat/completions
"""), env=SECRETS)
check("the summary may be enabled with no key at all",
      no_key.get("ai.enabled") is True)

msg = check_raises("a non-http api_url is refused", cfgmod.load,
                   write(MINIMAL + "\nai:\n  api_url: localhost:11434/v1\n"),
                   env=SECRETS)
check("the api_url message names the key", "api_url" in msg, msg)

msg = check_raises("an api_url blanked while enabled is refused", cfgmod.load,
                   write(MINIMAL + '\nai:\n  enabled: true\n  api_url: ""\n'),
                   env=SECRETS)
check("the blank api_url message names the key", "api_url" in msg, msg)

msg = check_raises("hour 24 does not exist", cfgmod.load,
                   write(MINIMAL + "\nai:\n  notify_at_hour: 24\n"), env=SECRETS)
check("the hour message names the key", "notify_at_hour" in msg, msg)

msg = check_raises("a topic cap of zero would send an empty prompt", cfgmod.load,
                   write(MINIMAL + "\nai:\n  max_per_topic: 0\n"), env=SECRETS)
check("the topic-cap message names the key", "max_per_topic" in msg, msg)

ai_on = cfgmod.load(write(MINIMAL + """
ai:
  enabled: true
  api_url: http://ollama.invalid:11434/v1/chat/completions
  model: qwen2.5
"""), env=dict(SECRETS, OPENAI_API_KEY="k"))
check("an OpenAI-compatible endpoint that is not OpenAI is accepted",
      ai_on.get("ai.api_url") == "http://ollama.invalid:11434/v1/chat/completions")
check("setting one ai key keeps the siblings",
      ai_on.get("ai.max_per_topic") == 5)


# --------------------------------------------------------------------------
# the committed template must satisfy its own contract
# --------------------------------------------------------------------------

example = pathlib.Path(__file__).resolve().parent.parent / "config" / "config.yaml.example"
if example.is_file():
    shipped = cfgmod.load(example, env=SECRETS)
    check("config.yaml.example loads and validates", shipped.get("feeds"))
    check("the shipped template enables at least one feed",
          len(shipped.enabled_feeds()) > 0)
    check("no secret is present in the committed template",
          not any(k in str(shipped.as_dict()) for k in SECRETS))
    # The default is 0 (an absent key keeps everything, so an upgrade never
    # starts deleting on its own); the template ships the bounded window, which
    # is the half of P6's "no disk growth" a config file can answer.
    check("the shipped template bounds the archive at 90 days",
          shipped.get("storage.retention_days") == 90,
          repr(shipped.get("storage.retention_days")))
    check("an absent retention_days still keeps everything",
          cfg.get("storage.retention_days") == 0)
    check("the template ships the heartbeat off, url to be filled in locally",
          shipped.get("ops.heartbeat_url") == "")
    # The template loads with no OPENAI_API_KEY in `SECRETS`, which only holds
    # because it ships the summary off. That is the check, not the value.
    check("the template ships the summary off, so it needs no API key",
          shipped.get("ai.enabled") is False, repr(shipped.get("ai.enabled")))
else:
    FAILURES.append("config/config.yaml.example is missing from the checkout")


# --------------------------------------------------------------------------

if FAILURES:
    print("FAIL - {} check(s):".format(len(FAILURES)))
    for f in FAILURES:
        print("  - {}".format(f))
    sys.exit(1)

print("OK")
