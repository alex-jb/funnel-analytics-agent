"""Tests for the PH-day milestone tracker.

State persistence (the high-water mark file) is the tricky bit — these
tests redirect it to tmp_path so concurrent test runs don't stomp on
each other.
"""
from __future__ import annotations
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.milestones import (
    VIBEX_MILESTONE_THRESHOLDS,
    check_crossing,
)


def test_first_crossing_returns_threshold_and_tweet(tmp_path):
    state = tmp_path / "state.json"
    result = check_crossing("vibex_total_upvotes", 105, state_path=state)
    assert result is not None
    threshold, tweet = result
    assert threshold == 100
    assert "100 upvotes" in tweet
    assert "producthunt.com" in tweet


def test_no_crossing_returns_none(tmp_path):
    state = tmp_path / "state.json"
    # 99 < first threshold (100)
    assert check_crossing("vibex_total_upvotes", 99, state_path=state) is None


def test_same_milestone_fires_once(tmp_path):
    state = tmp_path / "state.json"
    first = check_crossing("vibex_total_upvotes", 105, state_path=state)
    assert first is not None
    # Same value → no re-fire
    second = check_crossing("vibex_total_upvotes", 105, state_path=state)
    assert second is None
    # Higher but still below 500 → no re-fire (we already crossed 100)
    third = check_crossing("vibex_total_upvotes", 250, state_path=state)
    assert third is None


def test_jumping_past_multiple_thresholds_returns_highest(tmp_path):
    """If a single fetch jumps past 100 AND 500, return 500 (the higher
    one). That's the most-newsworthy milestone to celebrate."""
    state = tmp_path / "state.json"
    result = check_crossing("vibex_total_upvotes", 600, state_path=state)
    assert result is not None
    threshold, tweet = result
    assert threshold == 500


def test_unknown_metric_returns_none(tmp_path):
    state = tmp_path / "state.json"
    assert check_crossing("unknown_metric", 999, state_path=state) is None


def test_state_persistence(tmp_path):
    state = tmp_path / "state.json"
    check_crossing("vibex_total_upvotes", 105, state_path=state)
    raw = json.loads(state.read_text())
    assert raw["vibex_total_upvotes"] == 105


def test_corrupt_state_file_treated_as_empty(tmp_path):
    """A garbage state file (e.g. interrupted write) shouldn't crash
    the agent — treat as empty and proceed."""
    state = tmp_path / "state.json"
    state.write_text("not json at all {")
    result = check_crossing("vibex_total_upvotes", 105, state_path=state)
    # Should still fire as if first run
    assert result is not None
    assert result[0] == 100


def test_all_vibex_thresholds_have_tweets():
    """Every configured metric should have a non-empty template."""
    for metric, (thresholds, template) in VIBEX_MILESTONE_THRESHOLDS.items():
        assert thresholds
        assert template
        # Template must include {value} placeholder
        assert "{value}" in template
        # And rendered tweet should fit X's 280-char limit (with biggest threshold)
        biggest = max(thresholds)
        rendered = template.format(value=biggest)
        assert len(rendered) <= 280, (
            f"{metric} template at {biggest} renders to {len(rendered)} chars "
            f"(>280). Trim it."
        )
