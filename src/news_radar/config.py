"""Load and validate config.yaml, and check the secrets it implies.

A leaf module: it imports nothing else from the package. The object it returns
never holds a secret - `notify/*` reads those straight from the environment - so
a Config is safe to log in full.

Contract: docs/memory-ai/interface/config-and-env.md
"""

from __future__ import annotations

import os
from pathlib import Path

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
