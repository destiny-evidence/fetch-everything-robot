"""Data models to record performance of fer on test datasets."""

import contextlib
import json
import os
import platform
import time
from pathlib import Path
from typing import Final

from loguru import logger
from pydantic import BaseModel, Field

from fer.config import ExternalAPI, Settings, external_api_priority
from fer.fetch_fulltext import FullTextResult

BADGE_OUTPUT_PATH = Path("metrics/fetch_badge.json")
HISTORY_JSON_PATH = Path("metrics/metrics.json")

BADGE_THRESHOLDS: Final[list[tuple[float, str]]] = [
    (80.0, "brightgreen"),
    (50.0, "yellow"),
    (0.0, "red"),
]


class ConfigSnapshot(BaseModel):
    """Captures context where test was run."""

    runner: str = Field(
        description="The execution context (e.g., GitHub Actions or local user machine)"
    )
    env: str = Field(description="The application deployment environment setting")
    batch_size: int = Field(
        description="Number of references included per batch iteration"
    )
    has_scopus_key: bool = Field(description="Presence flag for Scopus API key")
    has_scopus_inst_token: bool = Field(
        description="Presence flag for Scopus institutional token"
    )
    has_openalex_key: bool = Field(description="Presence flag for OpenAlex API key")
    has_scopus_proxy: bool = Field(
        description="Presence flag for custom Scopus request proxy routing"
    )

    @classmethod
    def capture(cls, settings: Settings) -> "ConfigSnapshot":
        """Discover and snapshot the current running environment."""
        if os.environ.get("GITHUB_ACTIONS") == "true":
            runner_profile = "GitHub Actions"
        else:
            try:
                username = (
                    os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
                )
                hostname = platform.node() or "localhost"
                runner_profile = f"local ({username}@{hostname})"
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Failed to resolve system context {e}")
                runner_profile = "local (unknown context)"

        return cls(
            runner=runner_profile,
            env=str(settings.env),
            batch_size=settings.batch_size,
            has_scopus_key=bool(
                settings.elsevier_scopus_key
                and settings.elsevier_scopus_key.get_secret_value()
            ),
            has_scopus_inst_token=bool(
                settings.elsevier_scopus_inst_token
                and settings.elsevier_scopus_inst_token.get_secret_value()
            ),
            has_openalex_key=bool(
                settings.openalex_key and settings.openalex_key.get_secret_value()
            ),
            has_scopus_proxy=bool(settings.scopus_proxy_url),
        )


class GlobalMetrics(BaseModel):
    """Total pdf retrieval metrics across sources."""

    total_dois: int = Field(
        description="Total count of DOIs evaluated in this flight run"
    )
    success_count: int = Field(
        description="Count of PDFs successfully fetched and verified"
    )
    success_rate: float = Field(description="Fraction of fetch conversions (0.0 - 1.0)")


class SourceMetrics(BaseModel):
    """Metrics for each source."""

    attempts: int = Field(description="Number of times this specific API was invoked")
    successes: int = Field(
        description="Number of times this specific API successfully yielded a PDF"
    )
    rate: float = Field(description="Conversion rate per attempt (0.0 - 100.0)")


class EvaluationRunEntry(BaseModel):
    """An entry of an evaluation run."""

    timestamp: str = Field(
        description="Date and time mark of the evaluation run execution"
    )
    commit: str = Field(description="Truncated 7-character Git commit identifier hash")
    config: ConfigSnapshot = Field(
        description="The detailed software config context of this run"
    )
    overall: GlobalMetrics = Field(
        description="Aggregated top-level target summary counts"
    )
    by_source: dict[str, SourceMetrics] = Field(
        description="Granular evaluation strategy metrics breakdown"
    )

    @classmethod
    def from_results(
        cls, results: list[FullTextResult], settings: Settings
    ) -> "EvaluationRunEntry":
        """Create metrics instance from results of running local robot."""
        total_count = len(results)
        if total_count == 0:
            no_results = "Cannot generate evaluation entry from empty results list."
            raise ValueError(no_results)

        success_count = sum(1 for r in results if r.fulltext_path is not None)
        success_rate = success_count / total_count
        overall_metrics = GlobalMetrics(
            total_dois=total_count,
            success_count=success_count,
            success_rate=success_rate,
        )

        enabled_apis = list(ExternalAPI.__members__.values())
        priority_map = external_api_priority.priorities
        sorted_strategies = sorted(
            enabled_apis, key=lambda api: priority_map.get(api, 99)
        )
        strategy_counts = {
            str(api): {"attempts": 0, "successes": 0} for api in sorted_strategies
        }

        for r in results:
            raw_source = r.source
            winning_source = str(raw_source).strip().lower() if raw_source else None
            is_success = r.fulltext_path is not None

            for api_str, counts in strategy_counts.items():
                if is_success and winning_source == api_str:
                    counts["attempts"] += 1
                    counts["successes"] += 1
                    break

                counts["attempts"] += 1

        by_source_metrics = {}
        for source, data in strategy_counts.items():
            attempts = data["attempts"]
            successes = data["successes"]
            rate = round((successes / attempts) * 100, 2) if attempts > 0 else 0.0
            by_source_metrics[source] = SourceMetrics(
                attempts=attempts, successes=successes, rate=rate
            )

        return cls(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            commit=os.environ.get("GITHUB_SHA", "local-run")[:7],
            config=ConfigSnapshot.capture(settings),
            overall=overall_metrics,
            by_source=by_source_metrics,
        )

    def save(self) -> None:
        """
        Save metrics and shield json.

        Keep one entry for each unique commit and configuration combination.
        """
        success_rate = self.overall.success_rate
        colour = next(
            (
                tier_colour
                for threshold, tier_colour in BADGE_THRESHOLDS
                if success_rate >= threshold
            ),
            BADGE_THRESHOLDS[-1][1],
        )

        fraction = f"({self.overall.success_count}/{self.overall.total_dois})"

        shields_payload = {
            "schemaVersion": 1,
            "label": "pdf fetch rate",
            "message": f"{success_rate:.0%} {fraction}",
            "color": colour,
            "style": "flat-square",
        }

        BADGE_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with BADGE_OUTPUT_PATH.open("w") as f:
            json.dump(shields_payload, f, indent=2)

        history_list = []
        if HISTORY_JSON_PATH.exists():
            with (
                HISTORY_JSON_PATH.open() as f,
                contextlib.suppress(json.JSONDecodeError),
            ):
                history_list = json.load(f)

        duplicate_index = None
        for index, entry in enumerate(history_list):
            if (
                entry.get("commit") == self.commit
                and entry.get("config", {}).get("runner") == self.config.runner
            ):
                duplicate_index = index
                break

        if duplicate_index is not None:
            history_list[duplicate_index] = self.model_dump()
        else:
            history_list.append(self.model_dump())

        with HISTORY_JSON_PATH.open("w") as f:
            json.dump(history_list, f, indent=2)
