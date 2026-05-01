"""PH-day milestone tracker.

Persists last-seen gauge values to ~/.funnel-analytics-agent/milestones.json
and detects threshold crossings on each fetch. When a threshold is crossed,
returns a pre-written celebration tweet body alongside the milestone label.

The agent's notifier fan-out picks up these alert-severity metrics
(ntfy / Telegram / Slack) — Alex's phone buzzes with the ready-to-send
tweet text. Zero X creds required, zero risk of spam-tweet from a flaky
metric (the human still hits Send).

Persistence is simple JSON: {metric_name: highest_seen_value}. Only the
high-water mark matters; a transient dip in `total_upvotes` (e.g. PH
data lag) won't re-fire a milestone we already crossed.
"""
from __future__ import annotations
import json
import pathlib
from typing import Optional


DEFAULT_STATE_PATH = (pathlib.Path.home()
                       / ".funnel-analytics-agent" / "milestones.json")

# Each metric maps to (thresholds, tweet template).
# Template gets {value} substituted and is hard-capped at 280 chars elsewhere.
VIBEX_MILESTONE_THRESHOLDS = {
    "vibex_total_upvotes": (
        [100, 500, 1000, 2500, 5000],
        "🔨 {value} upvotes on @ProductHunt — VibeXForge is climbing.\n\n"
        "Forge your AI project into a 16-bit hero. Evolve from Seed to Myth.\n\n"
        "https://www.producthunt.com/posts/vibexforge",
    ),
    "vibex_total_plays": (
        [500, 2500, 10_000, 50_000],
        "🎮 {value} plays on VibeXForge today.\n\n"
        "Real makers shipping real AI projects. Submit yours, get forged "
        "into a hero card, evolve from Seed to Myth.\n\n"
        "https://www.vibexforge.com",
    ),
    "vibex_total_creators": (
        [50, 250, 1000],
        "👥 {value} makers have signed up to forge their AI projects "
        "on VibeXForge.\n\nIf you've shipped something this month, "
        "drop it in: https://www.vibexforge.com",
    ),
    "vibex_myth_count": (
        [1, 3, 10],
        "✨ {value} project(s) at MYTH stage on VibeXForge.\n\n"
        "10k plays. 1k upvotes. 90+ Claude score. Real traction.\n\n"
        "Top of leaderboard: https://www.vibexforge.com",
    ),
}


def _load_state(path: pathlib.Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text()) or {}
    except Exception:
        return {}


def _save_state(path: pathlib.Path, state: dict[str, int]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2))
    except Exception:
        # Best-effort — never fail the agent because the milestone log is unwritable
        pass


def check_crossing(
    metric: str,
    value: int,
    *,
    state_path: pathlib.Path = DEFAULT_STATE_PATH,
    thresholds_map: dict | None = None,
) -> Optional[tuple[int, str]]:
    """If `value` crosses a threshold for `metric` that wasn't crossed before,
    return (threshold, tweet_text). Otherwise None.

    Updates the state file on a successful crossing so the same milestone
    fires only once.
    """
    thresholds_map = thresholds_map or VIBEX_MILESTONE_THRESHOLDS
    config = thresholds_map.get(metric)
    if not config:
        return None
    thresholds, template = config

    state = _load_state(state_path)
    last_seen = int(state.get(metric, 0))

    # Find the highest threshold crossed by current value AND not yet crossed
    crossed: Optional[int] = None
    for t in thresholds:
        if value >= t and last_seen < t:
            crossed = t  # keep going to find the highest
    if crossed is None:
        return None

    # Persist the new high-water mark
    state[metric] = max(last_seen, value)
    _save_state(state_path, state)

    tweet = template.format(value=crossed)
    return crossed, tweet
