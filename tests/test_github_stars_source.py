"""Tests for GithubStarsSource."""
from __future__ import annotations
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.sources.github_stars import GithubStarsSource


def _fake_urlopen(payload):
    fake = MagicMock()
    fake.read.return_value = json.dumps(payload).encode()
    fake.__enter__ = lambda s: s
    fake.__exit__ = lambda *a: None
    return fake


def test_uses_default_repos_when_no_env(monkeypatch):
    monkeypatch.delenv("GITHUB_STARS_REPOS", raising=False)
    src = GithubStarsSource()
    repos = src._repos()
    assert "alex-jb/solo-founder-os" in repos
    assert len(repos) >= 8


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("GITHUB_STARS_REPOS",
                        "test/repo1, test/repo2, test/repo3")
    src = GithubStarsSource()
    assert src._repos() == ["test/repo1", "test/repo2", "test/repo3"]


def test_renders_stars_and_forks_per_repo(monkeypatch):
    monkeypatch.setenv("GITHUB_STARS_REPOS", "alex-jb/solo-founder-os")
    fake = _fake_urlopen({
        "stargazers_count": 42,
        "forks_count": 7,
        "html_url": "https://github.com/alex-jb/solo-founder-os",
        "open_issues_count": 3,
    })
    with patch("urllib.request.urlopen", return_value=fake):
        r = GithubStarsSource().fetch()
    assert r.error is None
    by_name = {m.name: m for m in r.metrics}
    assert by_name["github_stars_alex_jb_solo_founder_os"].value == 42
    assert by_name["github_forks_alex_jb_solo_founder_os"].value == 7
    # Total
    assert by_name["github_stars_total"].value == 42


def test_aggregates_total_across_multiple_repos(monkeypatch):
    monkeypatch.setenv("GITHUB_STARS_REPOS",
                        "alex-jb/repo1,alex-jb/repo2,alex-jb/repo3")
    # Return different star counts per call
    counts = [10, 25, 5]
    forks = [1, 2, 0]

    call_idx = {"i": 0}

    def fake_open(req, timeout=None):
        i = call_idx["i"]
        call_idx["i"] += 1
        return _fake_urlopen({
            "stargazers_count": counts[i],
            "forks_count": forks[i],
            "html_url": f"https://github.com/alex-jb/repo{i+1}",
        })

    with patch("urllib.request.urlopen", side_effect=fake_open):
        r = GithubStarsSource().fetch()
    total = [m for m in r.metrics if m.name == "github_stars_total"][0]
    assert total.value == 40  # 10 + 25 + 5


def test_partial_failure_doesnt_break_source(monkeypatch):
    """If one repo lookup fails, we still return the others. The source
    only errors if ALL fail."""
    monkeypatch.setenv("GITHUB_STARS_REPOS", "alex-jb/good,alex-jb/bad")
    call_idx = {"i": 0}

    def fake_open(req, timeout=None):
        i = call_idx["i"]
        call_idx["i"] += 1
        if i == 0:
            return _fake_urlopen({"stargazers_count": 10, "forks_count": 1})
        raise Exception("404 or rate limited")

    with patch("urllib.request.urlopen", side_effect=fake_open):
        r = GithubStarsSource().fetch()
    assert r.error is None
    # The bad repo doesn't appear, the good one does
    names = {m.name for m in r.metrics}
    assert "github_stars_alex_jb_good" in names
    assert "github_stars_alex_jb_bad" not in names


def test_all_failures_returns_error(monkeypatch):
    monkeypatch.setenv("GITHUB_STARS_REPOS", "alex-jb/a,alex-jb/b")
    with patch("urllib.request.urlopen", side_effect=Exception("ratelimit")):
        r = GithubStarsSource().fetch()
    assert r.error is not None
    assert "rate limited" in r.error.lower() or "GITHUB_TOKEN" in r.error


def test_token_added_to_auth_header(monkeypatch):
    monkeypatch.setenv("GITHUB_STARS_REPOS", "alex-jb/test")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_xxxxxxxxxxxxxxxx")
    captured = {}

    def fake_open(req, timeout=None):
        captured["headers"] = dict(req.headers)
        return _fake_urlopen({"stargazers_count": 1, "forks_count": 0})

    with patch("urllib.request.urlopen", side_effect=fake_open):
        GithubStarsSource().fetch()
    auth = captured["headers"].get("Authorization", "")
    assert "Bearer ghp_xxxx" in auth
