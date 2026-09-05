"""The fetch layer: everything that talks to a source and nothing that decides.

Three modules, in dependency order:

- `http`   - the transport. Standard library only, imports nothing from the
             package: User-Agent, timeout, retries, per-hostname throttle.
- `feeds`  - RSS / Atom / HN Algolia JSON into NewsItem, plus the fixed-feed
             reader and the one place a source failure is caught.
- `search` - each keyword group's primary term expanded into the enabled
             search templates, fetched through `feeds`.

Layering: docs/memory-ai/architecture/module-layout.md
"""
