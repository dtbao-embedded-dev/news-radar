---
title: "ADR-0001: Clean-room reimplementation, TrendRadar as reference only"
category: architecture
purpose: Why news-radar is written from scratch instead of forking TrendRadar, and what that forbids.
status: active
updated: 2026-09-04
source: conversation, https://github.com/sansan0/TrendRadar
confidence: confirmed
keywords: ADR-0001, clean-room, TrendRadar, GPL-3.0, license, fork, copyleft, reference
order: 1
---

# ADR-0001: Clean-room reimplementation, TrendRadar as reference only

> news-radar solves the same problem as TrendRadar and is written from zero
> anyway. TrendRadar is read to learn *how* a problem was solved; nothing is
> copied across.

## Status

Accepted, 2026-09-04.

## Context

`https://github.com/sansan0/TrendRadar` is a mature, widely used project (62k
stars) that aggregates trending stories, filters them by a keyword file, renders
an HTML report and pushes to a list of chat channels. news-radar wants the same
shape of system, aimed at different sources and a different audience.

Two facts decide the approach:

1. **TrendRadar is licensed GPL-3.0** (verified via the GitHub API:
   `license.spdx_id == "GPL-3.0"`). Deriving from it makes the derivative work
   subject to the same copyleft.
2. **The requirements differ where it matters.** news-radar targets English and
   Vietnamese technology feeds via RSS plus keyword-built search feeds; TrendRadar
   targets Chinese hot-lists through the newsnow API. Its notification set, its
   AI layer and its storage backends are all wider than needed here. A fork would
   start with more code to delete than to keep.

## Decision

Write news-radar from scratch. Treat TrendRadar as **documentation**: read it
when a specific problem is hard, understand the approach, then implement our own.

**Allowed to carry across:** an approach, stated in words — "ranking is a
weighted sum of rank, cross-source frequency and hotness", "the keyword file uses
a blank line to separate independent groups".

**Not allowed to carry across:** source code, function or module names, file
layout, constant values, message-format strings, or a configuration schema copied
key-for-key.

## Consequences

- news-radar stays free to pick its own license. **No `LICENSE` file exists yet**
  — that decision is still open and must be made before the repository is made
  public.
- No upstream merges. Every fix TrendRadar makes has to be re-derived here if it
  applies. That cost is accepted and is why the reference rule exists at all.
- Problems already solved upstream get solved again. The mitigation is
  [[reference-trendradar]]: a table of "stuck on X, go read Y", so the second
  implementation is informed rather than blind.
- Design docs in this bank describe news-radar's own design. Where a doc records
  an idea learned from TrendRadar, it says so in prose and does not reproduce the
  upstream artifact.
