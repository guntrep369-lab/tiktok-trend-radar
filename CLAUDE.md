# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

TikTok Trend Radar — a serverless pipeline that pulls Google Trends data every 3 hours,
computes velocity/acceleration to classify each keyword's meme-lifecycle phase, alerts via
LINE when something is surging, and publishes a static dashboard to GitHub Pages. Everything
runs free on GitHub Actions; there is no server and no database — state lives in committed
data files. Most code comments and user-facing strings are in Thai.

> Note on layout: the actual project root (with `.git`, `config.json`, `scripts/`) is nested
> one level below the Claude working directory, at `tiktok-trend-radar/tiktok-trend-radar/`.
> Run commands from that nested directory.

## Commands

```bash
pip install -r requirements.txt

# Run the full pipeline with simulated data (no network, deterministic-ish — use for logic testing)
python scripts/run_radar.py --mode simulate

# Run against real Google Trends (what GitHub Actions runs)
python scripts/run_radar.py --mode live

# Test LINE delivery locally (otherwise notification is silently skipped)
export LINE_CHANNEL_ACCESS_TOKEN="..."
export LINE_USER_ID="..."
python scripts/run_radar.py --mode simulate

# Feedback loop / ROI tracking (LOCAL ONLY — data is gitignored, never published)
python scripts/campaign_tracker.py log --video-id V1 --keyword "คอลลาเจน"
python scripts/campaign_tracker.py update --video-id V1 --views 18000 --orders 31 --gmv 9300
python scripts/campaign_tracker.py import --file affiliate_export.csv   # bulk from TikTok Shop CSV
python scripts/campaign_tracker.py report                                # ROI per keyword/mood
python scripts/campaign_tracker.py weights                               # derive roi_weights.json (commit it)

# AI script generator (needs ANTHROPIC_API_KEY; writes a ready-to-shoot TikTok script)
export ANTHROPIC_API_KEY="sk-ant-..."
python scripts/script_generator.py --keyword "คอลลาเจน" --label GROWTH

# AI video pipeline (Veo + Thai TTS + ffmpeg -> YouTube; needs requirements-video.txt + ffmpeg)
python scripts/video_generator.py --keyword "อาหารเปียกแมว" --dry-run   # plan only, no cost
python scripts/video_generator.py --keyword "อาหารเปียกแมว" --out out/video.mp4  # costs money (Veo)
python scripts/youtube_uploader.py setup --client-id X --client-secret Y  # one-time OAuth
python scripts/youtube_uploader.py upload --file out/video.mp4            # uploads as private

# Kids' cartoon story mode (views play, not affiliate)
python scripts/story_generator.py --theme "แมวน้อยหัดแบ่งปัน" --scenes 5   # Claude writes the story
python scripts/video_generator.py --story-file out/story.json --out out/story.mp4
python scripts/video_generator.py --story-file out/story.json --clips-dir flow_clips/ --out out/story.mp4  # Flow hybrid: assemble downloaded clips, no Veo cost
# story uploads auto-set Made-for-Kids; manual flag: youtube_uploader.py upload --made-for-kids
```

```bash
# Tests (pytest). Install dev deps first:
pip install -r requirements-dev.txt
python -m pytest -q                       # whole suite
python -m pytest tests/test_trend_engine.py -q   # one file
python -m pytest -q -k cooldown           # one test by keyword
```

Tests live in `tests/` (a `conftest.py` puts `scripts/` on `sys.path` — there is no package).
They focus on the deterministic core: `_classify_trend` phase logic, `_resolve_patterns`,
`compute_velocity_acceleration`, `match_product`, and `filter_recent_alerts` cooldown. The
classifier reacts to only the last ~3 velocity points, so exact pattern→phase under random
noise is intentionally NOT asserted; instead one integration test asserts simulate produces
phase *variety*. `--mode simulate` remains the way to exercise the full pipeline end to end.

## Architecture

The pipeline is orchestrated by `scripts/run_radar.py:main()`. Data flows in one direction:

```
config.json (keyword_batches)
  → trend_engine.fetch_live_trend / simulate_trend_data   (pull interest-over-time)
  → trend_engine.compute_velocity_acceleration            (1st/2nd derivatives → phase label)
  → trend_engine.rank_keywords_by_momentum                (DataFrame indexed by keyword)
  → data/history.csv (append) + data/latest.json + docs/{latest,history}.json (overwrite)
  → run_radar.find_alerts → line_notifier (LINE push for GROWTH/PEAK only)
```

Key design points to understand before changing anything:

- **The "momentum" model lives in `trend_engine.compute_velocity_acceleration` and
  `_classify_trend`.** Velocity is the 1st derivative of a smoothed interest series,
  acceleration the 2nd. `momentum_score = 0.7*velocity + 0.3*acceleration`. `_classify_trend`
  maps (velocity, acceleration, current_score) to one of five phases: `INTRO`, `GROWTH`,
  `PEAK`, `DECLINE`, `STABLE`. The phase, not the raw score, drives alerting.

- **Only `GROWTH` and `PEAK` ever alert** (`trend_engine.ALERT_PHASES`), and only if
  `momentum_score >= momentum_alert_threshold` from config. Changing alert behavior means
  touching `ALERT_PHASES` and/or `find_alerts`, not the dashboard.

- **Alert de-dup** prevents spamming the same keyword every 3h while it sits in GROWTH/PEAK.
  `data/alert_state.json` (committed back to the repo) records the last-alert timestamp per
  keyword; `filter_recent_alerts` drops anything alerted within `alert_cooldown_hours`. State
  is only updated for keywords actually sent.

- **Keyword discovery** (`keyword_discovery.py`) IS now wired in: in `live` mode `run_discovery`
  surfaces trending/related candidate keywords, writes `data/suggestions.json` + `docs/suggestions.json`,
  and appends a "คำใหม่น่าจับตา" footer to the LINE alert. It is best-effort (wrapped in
  try/except) and never auto-adds to `config.json` — a human curates. The dashboard renders
  `suggestions.json` in a section that hides itself when the file is absent.

- **Live mode sleeps `batch_delay_seconds` between batches** to reduce Google Trends 429s
  (`run_radar.main`). Simulate mode skips the delay and rotates a pattern per keyword
  (`viral_spike/plateauing/emerging/dying/noise`) so all five phases appear — useful for
  exercising the classifier and dashboard offline.

- **`live` mode degrades gracefully, never crashes the pipeline.** `fetch_live_trend` retries
  with exponential backoff (handles Google 429s); if a batch still fails it falls back to
  `simulate_trend_data(pattern="noise")` and tags `source="simulate_fallback"`. A batch that
  throws is logged and skipped; the run only exits non-zero if *every* batch fails. pytrends
  is an unofficial scraper, so live failures are expected and normal.

- **State is files committed back to the repo, not a DB.** `history.csv` is append-only
  (one block of rows per run, keyed by `run_timestamp`) and written with `utf-8-sig` so Excel
  reads Thai correctly; `prune_history` caps it to the last `max_history_runs` runs each cycle
  so it can't grow forever. `latest.json`/`history.json`/`alert_state.json`/`suggestions.json`
  are overwritten each run. The Actions job commits `data/` and `docs/` back to `main` after
  each run — that commit is how the dashboard gets new data.

- **`docs/` is the published artifact.** `run_radar.py` writes copies of `latest.json` and a
  derived `history.json` (last 50 runs, via `build_history_json`) into `docs/` specifically so
  the static `docs/index.html` dashboard can `fetch()` them from GitHub Pages. If you change
  the JSON shape, update `docs/index.html` too — it reads `label`, `current_score`,
  `momentum_score`, and `product_suggestion` directly. Each card also draws a per-keyword
  score sparkline from `history.json`; because cards render before history loads, `loadHistory`
  re-calls `render` once the data arrives.

- **Meme→product mapping** (`meme_product_map.py`) is a keyword-substring heuristic, not AI.
  `match_product` scores each keyword against per-mood `signals` lists and returns the best
  match (or `DEFAULT_SUGGESTION`). It is attached to every result in `latest.json` and to
  alert messages so the dashboard/LINE can suggest what to sell.

- **Real product catalog** (`product_catalog.py` + `data/product_catalog.json`) upgrades the
  generic category above into a *specific* TikTok Shop product with affiliate link + commission %.
  TikTok Shop has no public API for a creator's affiliate links, so the catalog is a
  human-curated JSON the user maintains (starter examples committed with `REPLACE_ME` links).
  `match_affiliate_product(keyword, mood_key)` matches by catalog `keywords` first, then falls
  back to `moods`; returns `None` when nothing matches, so the pipeline degrades to the generic
  category. The matched product is attached to `latest.json` records (`affiliate_product`) and to
  alerts, surfaced on the dashboard card (name + commission + "เปิดลิงก์ขายเลย" button) and in
  LINE (name + commission + link), and passed to `script_generator` so Claude names the real
  product. The catalog is **committed** (unlike ROI data) because CI/LINE need it — affiliate
  links are shareable; the user can omit `commission_pct` if they consider it sensitive.

- **`keyword_discovery.py` is a standalone helper, not wired into the pipeline.** It surfaces
  candidate new keywords (trending searches + related suggestions) for a human to manually add
  to `config.json`. Nothing calls it automatically.

- **AI script generation** (`script_generator.py`, Anthropic SDK) turns an alert into a
  ready-to-shoot TikTok affiliate script (hook / shots / caption / hashtags / CTA / copyright-safe
  audio idea). Model defaults to `claude-opus-4-8` (configurable via `script_model`). It uses
  `messages.create` + a tolerant JSON extractor (`_parse_response`) rather than the structured-output
  API, so it works across SDK versions. Best-effort: `generate_script` returns `None` when
  `anthropic` isn't installed, `ANTHROPIC_API_KEY` is unset, or the call/parse fails — the pipeline
  never crashes. In `run_radar`, `run_script_generation` generates for the top `script_gen_max`
  fresh alerts, saves to `data/scripts.json` (**gitignored** — not published), and the hook+CTA are
  appended to the LINE alert. The pure functions (`_build_prompt`, `_parse_response`,
  `format_script_text`) are unit-tested offline; the live API call is not.

- **AI video pipeline (`video_generator.py` + `youtube_uploader.py`) is manual-trigger only —
  deliberately NOT wired into the 3-hour cron because Veo bills per clip.** Flow: script (Claude,
  reused) → English scene prompts (Claude with a pure `fallback_scene_prompts` template when no
  key) → Google Veo text-to-video (needs `GEMINI_API_KEY`; model id in config `video_model` —
  Veo ids rotate, check ai.google.dev if 404) → Thai voiceover via edge-tts (free,
  `video_tts_voice`) → ffmpeg: normalize 1080x1920 → concat → burn ASS subtitles (libass handles
  Thai shaping; drawtext does not) → replace Veo audio with the TTS track. Uploads via YouTube
  Data API as **private** (unaudited API projects get locked private anyway; the user publishes
  from Studio — that's the review gate). Upload costs 1600 of the 10k daily quota (~6/day max).
  Heavy deps live in `requirements-video.txt` so main CI stays lean; both modules lazy-import
  them, and tests cover only the pure parts (prompts/subtitles/metadata). Workflow:
  `video_factory.yml` (workflow_dispatch; needs secrets `GEMINI_API_KEY`, `YT_CLIENT_ID`,
  `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`; mp4 also saved as an Actions artifact). `out/` is
  gitignored.

- **Story Studio** (`docs/studio.html`) is a no-CLI web UI for the story lane, served on the same
  GitHub Pages site. It calls the Anthropic API **directly from the browser** (header
  `anthropic-dangerous-direct-browser-access: true`; the user's key lives in localStorage only —
  never in the repo) to write a story, then renders copy-ready Flow prompts and a story.json
  download. Its `buildStoryPrompt`/`parseStory`/`scenePrompts`/`STYLE` are a **JS duplicate of
  `story_generator.py`** — keep the two in sync when changing the story schema or channel style.
  Assembly/upload still happen via CLI/Actions (browsers can't run ffmpeg/YouTube OAuth sanely).

- **Kids' story mode** (`story_generator.py` + `--story-file` on video_generator) targets views
  instead of affiliate. Claude writes a story JSON (title/characters/moral/scenes/hashtags);
  the key constraint is **character consistency** — `story_scene_prompts` re-injects the full
  English character descriptions + a fixed channel style into *every* scene prompt, and
  `character_sheet_prompt` produces a reference-image prompt for Flow's ingredients feature.
  `--clips-dir` assembles pre-downloaded clips (e.g. from Google Flow, which has no API but
  better character control + subscription pricing) instead of calling Veo — the Flow-hybrid
  path. Story uploads have **no affiliate link** and default `made_for_kids=True`
  (`selfDeclaredMadeForKids`, COPPA) — kids content earns far less per view (no personalized
  ads); the affiliate lane remains the money maker.

- **Feedback loop / ROI (`campaign_tracker.py`) is a LOCAL, private tool — not part of the CI
  pipeline.** It links posted videos → source keyword → real TikTok Shop performance
  (views/clicks/orders/gmv) and aggregates ROI per keyword and per mood (`aggregate_performance`
  is pure and unit-tested). CLI: `log` / `update` / `import` (CSV from the affiliate dashboard,
  joined by `video_id`) / `report`. Mood is auto-derived via `match_product`. **Privacy:
  `data/campaigns.csv`, `data/performance.json`, and `docs/performance.json` are gitignored** so
  sales numbers are never committed or published to the (public) Pages site — the dashboard's
  "💰 ผลงานจริง (ROI)" panel only appears on a local preview and stays hidden publicly. This is
  the loop meant to eventually tune alert ranking by real revenue instead of Google momentum.

- **ROI-weighted ranking closes that loop.** `campaign_tracker weights` derives per-mood ROI
  multipliers (normalized gmv-per-video, clamped 0.5–2.0, min 3 videos/mood) into
  `data/roi_weights.json`. Unlike the raw ROI data this file is **committable** (relative
  multipliers only, no absolute sales) so CI can use it. `run_radar` loads it and
  `apply_roi_weights` sets `ranking_score = momentum_score × mood_weight` on every record/alert;
  alerts (LINE order + which get scripts) and the dashboard's "ROI" sort use `ranking_score`.
  No file → all weights 1.0 → identical to plain momentum ordering (safe default). The repo ships
  **no** `roi_weights.json`; the user generates and commits their own.

## Configuration

`config.json` drives everything: `geo`, `timeframe`, `momentum_alert_threshold`,
`keyword_batches`, plus `batch_delay_seconds` (live inter-batch sleep, default 8),
`alert_cooldown_hours` (alert de-dup window, default 12), and `enable_keyword_discovery`
(default true). Google Trends compares at most **5 keywords per batch** — keep each inner
list ≤ 5. More batches = higher rate-limit risk; README suggests ≤ 4–5 batches per run.

## Secrets / deployment

`LINE_CHANNEL_ACCESS_TOKEN` and `LINE_USER_ID` are read from env vars (GitHub Secrets in CI).
If either is missing, `send_line_message` logs a warning and returns `False` — it never raises,
so a missing token degrades to "no notification" rather than a failed run.

Two workflows in `.github/workflows/`: `trend_radar.yml` (cron `0 */3 * * *` + manual dispatch;
runs the pipeline, commits data, deploys Pages) and `deploy_pages.yml` (redeploys Pages on any
push touching `docs/**`). `deploy.sh` is a one-time bootstrap script (gh CLI: create repo, push,
set secrets).
