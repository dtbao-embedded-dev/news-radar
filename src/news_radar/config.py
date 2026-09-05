"""Load and validate config.yaml, and check the secrets it implies.

A leaf module: it imports nothing else from the package. The object it returns
never holds a secret - `__main__._notify()` reads those straight from the
environment and hands them to the channel - so a Config is safe to log in full.

Contract: docs/memory-ai/interface/config-and-env.md
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from . import __version__

ENV_CONFIG_PATH = "NEWS_RADAR_CONFIG"
DEFAULT_CONFIG_PATH = "config/config.yaml"

# Every key the contract documents, with the documented default. A key absent
# from config.yaml falls back to what is here; a key present there wins. Lists
# are replaced wholesale, never merged - half a feed list from two sources would
# be impossible to reason about.
DEFAULTS = {
    "app": {"timezone": "Asia/Ho_Chi_Minh"},
    "schedule": {"interval_minutes": 30, "run_on_start": True},
    "feeds": [],
    "search_templates": [],
    "keywords": {"file": "config/frequency_words.txt"},
    "report": {"mode": "incremental", "max_per_group": 0, "rank_threshold": 5},
    "rank": {
        "weight_source": 0.5,
        "weight_frequency": 0.3,
        "weight_freshness": 0.2,
        "freshness_half_life_hours": 12.0,
    },
    "storage": {"data_dir": "output", "retention_days": 0},
    # Everything that keeps the radar alive without being watched. All four ship
    # inert or safe: an absent `ops` section changes nothing about a run, which
    # is what lets an existing deployment upgrade into this version untouched.
    "ops": {
        "heartbeat_url": "",
        "site_url": "",
        "backup_dir": "backups",
        "backup_keep": 7,
    },
    # The AI summary (P6-4). Off, and therefore free: an existing config.yaml
    # that says nothing about `ai` upgrades into this version and behaves
    # exactly as it did before. The endpoint is spelled as a whole url rather
    # than a base, because the OpenAI *wire format* is what is being spoken -
    # OpenRouter, DeepSeek, Groq and a local Ollama all answer it, and only
    # some of them put it under `/v1`.
    "ai": {
        "enabled": False,
        "api_url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "max_per_topic": 5,
        "timeout_s": 60,
        "notify_at_hour": 8,
    },
    "notification": {
        "enabled": True,
        "channels": {
            "telegram": {"enabled": True},
            "discord": {"enabled": True},
        },
    },
    "advanced": {
        "request_interval_ms": 2000,
        "request_timeout_s": 15,
        "max_retries": 2,
        "user_agent": "news-radar/{version} (+https://news.dtbao.org)",
        "debug": False,
    },
}

# Channel -> the environment variables it cannot work without. Enabled with one
# of these missing is fatal, not a warning: a stack that starts and silently
# never notifies is the failure this project most wants to avoid.
REQUIRED_SECRETS = {
    "telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
    "discord": ("DISCORD_WEBHOOK_URL",),
}

REPORT_MODES = ("incremental", "current", "daily")


class ConfigError(Exception):
    """Refuse to start rather than run on a config that cannot do its job."""


def _is_http_url(url):
    """The same gate `Fetcher._request()` applies, checked where it is fixable."""
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def _merge(base, override):
    """Deep-merge dicts; anything else in `override` replaces outright."""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    out = dict(base)
    for key, value in override.items():
        out[key] = _merge(base.get(key), value) if key in base else value
    return out


class Config:
    """Dotted-path access over the merged mapping."""

    def __init__(self, data, path=None):
        self._data = data
        self.path = path

    def get(self, dotted, default=None):
        node = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def enabled_feeds(self):
        return [f for f in self.get("feeds", []) if f.get("enabled", True)]

    def enabled_search_templates(self):
        return [t for t in self.get("search_templates", []) if t.get("enabled", True)]

    def enabled_channels(self):
        """Channel names that are switched on, master switch included."""
        if not self.get("notification.enabled", True):
            return []
        channels = self.get("notification.channels", {}) or {}
        return [n for n, c in channels.items() if (c or {}).get("enabled", True)]

    def user_agent(self):
        template = self.get("advanced.user_agent") or ""
        return template.replace("{version}", __version__)

    def as_dict(self):
        return self._data


def config_path():
    """Where the config is read from: NEWS_RADAR_CONFIG, else the default."""
    return Path(os.environ.get(ENV_CONFIG_PATH) or DEFAULT_CONFIG_PATH)


def load(path=None, env=None):
    """Read, merge over the defaults, validate. Raises ConfigError.

    A missing file is fatal. Falling back to an all-default config would start a
    radar that hunts nothing and reports to no one, which looks like success.
    """
    env = os.environ if env is None else env
    path = Path(path) if path is not None else config_path()

    if not path.is_file():
        raise ConfigError(
            "config file not found: {} - run scripts/setup.py to create it "
            "from config/config.yaml.example".format(path))

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError("{} is not valid YAML: {}".format(path, exc)) from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("{} must contain a mapping at the top level".format(path))

    cfg = Config(_merge(DEFAULTS, raw), path=path)
    validate(cfg, env)
    return cfg


def validate(cfg, env=None):
    """Every reason to refuse to start, reported together rather than one per run."""
    env = os.environ if env is None else env
    problems = []

    interval = cfg.get("schedule.interval_minutes")
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
        problems.append(
            "schedule.interval_minutes must be an integer >= 1, got {!r}".format(interval))

    mode = cfg.get("report.mode")
    if mode not in REPORT_MODES:
        problems.append("report.mode must be one of {}, got {!r}".format(
            ", ".join(REPORT_MODES), mode))

    for name in ("weight_source", "weight_frequency", "weight_freshness"):
        value = cfg.get("rank." + name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            problems.append("rank.{} must be a number >= 0, got {!r}".format(name, value))

    # PyYAML implements YAML 1.1, where bare on/off/yes/no are booleans. An
    # `id: no` in config.yaml silently becomes False, and the id is the key
    # every source lookup, the report and the seen-set are built on - so a
    # non-string id has to be rejected here rather than found later.
    for section in ("feeds", "search_templates"):
        for index, entry in enumerate(cfg.get(section, []) or []):
            ident = entry.get("id")
            if not isinstance(ident, str) or not ident.strip():
                problems.append(
                    "{}[{}].id must be a non-empty string, got {!r}"
                    " (bare on/off/yes/no are YAML booleans - quote them)".format(
                        section, index, ident))
            if not (entry.get("url") or "").strip():
                problems.append("{}[{}].url is missing".format(
                    section, ident if isinstance(ident, str) else index))

    for template in cfg.get("search_templates", []) or []:
        url = template.get("url") or ""
        if url and "{kw}" not in url:
            problems.append(
                "search_templates[{}].url must contain {{kw}}: {!r}".format(
                    template.get("id", "?"), url))

    keep = cfg.get("ops.backup_keep")
    if not isinstance(keep, int) or isinstance(keep, bool) or keep < 0:
        problems.append(
            "ops.backup_keep must be an integer >= 0, got {!r}".format(keep))

    # A mistyped heartbeat url is the exact failure this section exists to
    # prevent: it would never reach the monitor, the monitor would never
    # complain about a ping it was not expecting, and the silent failure P6-1
    # is for would have grown a second hiding place.
    for name in ("heartbeat_url", "site_url"):
        url = cfg.get("ops." + name) or ""
        if url and not _is_http_url(url):
            problems.append(
                "ops.{} must be an http(s) url or empty, got {!r}".format(
                    name, url))

    # The summary's own numbers. `max_per_topic` has no zero case worth having:
    # zero titles a topic is a prompt with nothing in it and a bill for asking.
    for name, low, high in (("max_per_topic", 1, None),
                            ("timeout_s", 1, None),
                            ("notify_at_hour", 0, 23)):
        value = cfg.get("ai." + name)
        if (not isinstance(value, int) or isinstance(value, bool)
                or value < low or (high is not None and value > high)):
            problems.append("ai.{} must be an integer {}, got {!r}".format(
                name, ">= {}".format(low) if high is None
                else "between {} and {}".format(low, high), value))

    api_url = cfg.get("ai.api_url") or ""
    if api_url and not _is_http_url(api_url):
        problems.append(
            "ai.api_url must be an http(s) url, got {!r}".format(api_url))

    # The url is required when the summary is on; the *key* deliberately is not.
    # That is where this section parts company with the notification rule below:
    # a channel genuinely cannot work without its secret, while an SGLang, vLLM
    # or Ollama on the LAN authenticates nobody. Refusing to start would be this
    # file telling the operator their own server does not exist. A remote
    # endpoint with no key answers 401, and `summarize()` logs that every cycle -
    # visible, which is the property the fatal check was really protecting.
    if cfg.get("ai.enabled") and not api_url:
        problems.append("ai.enabled is true but ai.api_url is empty")

    # The one rule the whole project cares most about.
    for channel in cfg.enabled_channels():
        for var in REQUIRED_SECRETS.get(channel, ()):
            if not (env.get(var) or "").strip():
                problems.append(
                    "notification channel {!r} is enabled but {} is not set - "
                    "set it in docker/.env or disable the channel".format(channel, var))

    if not cfg.enabled_feeds() and not cfg.enabled_search_templates():
        problems.append("no feed and no search template is enabled - nothing to hunt")

    if problems:
        raise ConfigError("\n".join("  - " + p for p in problems))
