"""Data sources for the funnel analytics agent."""
from .base import MetricSample, Source, SourceReport
from .vercel import VercelSource
from .producthunt import ProductHuntSource
from .supabase import SupabaseAdvisorSource
from .openpanel import OpenPanelSource
from .hyperdx import HyperDXSource
from .buildquality import BuildQualitySource
from .agent_spend import AgentSpendSource
from .vibex import VibexSource
from .github_stars import GithubStarsSource

__all__ = [
    "MetricSample",
    "Source",
    "SourceReport",
    "VercelSource",
    "ProductHuntSource",
    "SupabaseAdvisorSource",
    "OpenPanelSource",
    "HyperDXSource",
    "BuildQualitySource",
    "AgentSpendSource",
    "VibexSource",
    "GithubStarsSource",
]
