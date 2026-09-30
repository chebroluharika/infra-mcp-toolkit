"""
Release Risk Predictor Service
==============================

AI-powered risk prediction for release milestones using Ollama LLM (Llama 3.2).
Compares current release metrics against historical data and uses
LLM to generate actionable insights.

REQUIRES: Ollama LLM to be configured and available.
No fallback mode - this is a pure AI-powered feature.

Features:
- Cross-release comparison at same milestone phase
- LLM-based probability reasoning
- LLM-generated risk analysis and action items
- Similarity matching to past releases
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from services.release_history import calculate_historical_averages, get_on_time_rate, get_similar_releases

logger = logging.getLogger(__name__)


def _get_ollama_config() -> Optional[Dict[str, str]]:
    """Read Ollama config from environment."""
    provider = os.getenv("ADK_LLM_PROVIDER", "")
    base_url = os.getenv("ADK_OLLAMA_BASE_URL", "").rstrip("/")
    api_token = os.getenv("ADK_OLLAMA_API_TOKEN", "")
    model = os.getenv("ADK_LLM_MODEL", "")
    auth_mode = os.getenv("ADK_OLLAMA_AUTH_MODE", "bearer")  # "bearer" or "bifrost"

    if provider == "ollama" and base_url and api_token and model:
        return {
            "base_url": base_url,
            "api_token": api_token,
            "model": model,
            "auth_mode": auth_mode,
        }

    missing = []
    if provider != "ollama":
        missing.append(f"ADK_LLM_PROVIDER={provider!r} (expected 'ollama')")
    if not base_url:
        missing.append("ADK_OLLAMA_BASE_URL")
    if not api_token:
        missing.append("ADK_OLLAMA_API_TOKEN")
    if not model:
        missing.append("ADK_LLM_MODEL")

    logger.error("Ollama not configured. Missing: %s", ", ".join(missing))
    return None


def _get_auth_headers(api_token: str, auth_mode: str) -> Dict[str, str]:
    """Get authentication headers based on auth mode."""
    if auth_mode == "bearer":
        return {"Authorization": f"Bearer {api_token}"}
    else:
        # Legacy Bifrost auth
        return {"x-bf-vk": api_token}


RISK_ANALYSIS_PROMPT = """You are an AI release risk analyst. Your summaries MUST be QUANTITATIVE with specific numbers, not qualitative statements.

## RULES FOR SUMMARY:
BAD (qualitative): "team faces risks from test pass rate and build stability"
GOOD (quantitative): "17 bugs ÷ 11.3/day = 1.5 days to clear, leaving 3.5 days buffer. However, 44 open bugs may yield 2-4 late P0s."

## ALWAYS INCLUDE THESE CALCULATIONS IN SUMMARY:
1. Days to clear critical bugs: [bugs] ÷ [velocity] = X days
2. Buffer or deficit: [available days] - [days needed] = Y days buffer/deficit
3. Risk quantification: "X% of similar releases with these metrics slipped" OR "N open bugs historically yield M late blockers"

## OUTPUT FORMAT (valid JSON only):
{
    "summary": "2-3 sentences with NUMBERS. Format: '[RISK LEVEL]: [X bugs] at [Y velocity] = [Z days] to clear vs [W days] available ([buffer/deficit]). [Quantified risk statement].'",
    "risk_factors": [
        "17 bugs ÷ 11.3/day = 1.5 days needed, 3.5 days buffer - but velocity could drop",
        "44 open bugs: historically 5-10% become late P0s = 2-4 potential blockers",
        "No test pass rate data: releases without this metric slip 40% more often"
    ],
    "positive_factors": [
        "Velocity 11.3/day is 3.3x the 3.4/day minimum required",
        "Buffer of 3.5 days can absorb 2-3 late discoveries"
    ],
    "action_items": [
        {"priority": 1, "action": "Triage 44 open bugs to identify hidden P0/P1s before they're discovered late", "impact": "high"},
        {"priority": 2, "action": "Run test suite and report pass rate - unknown test health is a blind spot", "impact": "high"},
        {"priority": 3, "action": "Monitor velocity daily - if it drops below 5/day, escalate immediately", "impact": "medium"}
    ],
    "projection": {
        "days_to_clear_bugs": "17 ÷ 11.3 = 1.5 days",
        "buffer_days": "5 - 1.5 = 3.5 days buffer",
        "break_even_velocity": "17 ÷ 5 = 3.4 items/day minimum",
        "late_bug_estimate": "44 open bugs × 5-10% late P0 rate = 2-4 potential blockers"
    },
    "similar_release_analysis": "R134 had 15 bugs at this phase and shipped on-time. R132 had 22 bugs and slipped 3 days.",
    "probability_reasoning": "17 bugs with 11.3/day velocity = 1.5 days, well within 5-day window. 58% probability accounts for late discovery risk from 44 open bugs."
}
"""


@dataclass
class RiskPrediction:
    """Risk prediction result."""

    release_id: str
    current_phase: str
    days_to_milestone: int
    milestone: str
    probability: int
    risk_level: str
    confidence: str
    current_metrics: Dict[str, Any]
    historical_average: Dict[str, Any]
    similar_releases: List[Dict[str, Any]]
    ai_insights: Dict[str, Any]
    generated_at: str
    llm_model: str
    llm_latency_ms: int


class RiskPredictorError(Exception):
    """Error raised when risk prediction fails."""

    pass


class RiskPredictor:
    """
    Predicts release risk using Ollama LLM.

    This service REQUIRES Ollama to be configured and available.
    There is no fallback mode - it's designed to test pure LLM performance.
    """

    def __init__(self):
        cfg = _get_ollama_config()
        if cfg:
            self._base_url = cfg["base_url"]
            self._api_token = cfg["api_token"]
            self._model = cfg["model"]
            self._auth_mode = cfg.get("auth_mode", "bearer")
            self._configured = True
            logger.info(
                "RiskPredictor initialized with Ollama: %s (model: %s, auth: %s)",
                self._base_url,
                self._model,
                self._auth_mode,
            )
        else:
            self._base_url = ""
            self._api_token = ""
            self._model = ""
            self._auth_mode = "bearer"
            self._configured = False
            logger.error("RiskPredictor: Ollama NOT configured - predictions will fail")

    def is_configured(self) -> bool:
        """Check if Ollama is configured."""
        return self._configured

    async def _call_llm(self, prompt: str) -> tuple[str, int]:
        """
        Call Ollama Gateway for risk analysis.

        Returns:
            Tuple of (response_content, latency_ms)

        Raises:
            RiskPredictorError if LLM call fails
        """
        if not self._configured:
            raise RiskPredictorError(
                "Ollama LLM not configured. Set ADK_LLM_PROVIDER=ollama, "
                "ADK_OLLAMA_BASE_URL, ADK_OLLAMA_API_TOKEN, and ADK_LLM_MODEL in .env"
            )

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            **_get_auth_headers(self._api_token, self._auth_mode),
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": RISK_ANALYSIS_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 1500,
        }

        start_time = time.time()
        max_retries = 4
        last_error = None
        retry_delays = [2, 5, 10]

        for attempt in range(max_retries):
            try:
                logger.info(
                    "Calling Ollama for risk analysis (attempt %d/%d): model=%s, prompt_len=%d",
                    attempt + 1,
                    max_retries,
                    self._model,
                    len(prompt),
                )

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=180),
                    ) as resp:
                        latency_ms = int((time.time() - start_time) * 1000)

                        if resp.status == 200:
                            data = await resp.json()
                            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                            logger.info(
                                "Ollama response received: %d chars in %dms (model: %s)",
                                len(content),
                                latency_ms,
                                self._model,
                            )

                            if not content:
                                raise RiskPredictorError("Ollama returned empty response")

                            return content, latency_ms

                        error_text = await resp.text()
                        last_error = f"Ollama returned status {resp.status}: {error_text[:200]}"
                        logger.warning("Ollama error (attempt %d): %s", attempt + 1, last_error)

                        is_retryable = (
                            resp.status >= 500 or resp.status == 400 and "closed connection" in error_text.lower()
                        )

                        if is_retryable and attempt < max_retries - 1:
                            delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                            logger.info("Retrying in %ds...", delay)
                            await asyncio.sleep(delay)
                            continue

                        raise RiskPredictorError(last_error)

            except aiohttp.ClientConnectorError as e:
                last_error = f"Cannot connect to Ollama at {self._base_url}: {e}"
                logger.warning("Connection error (attempt %d): %s", attempt + 1, last_error)
                if attempt < max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                    logger.info("Retrying in %ds...", delay)
                    await asyncio.sleep(delay)
                    continue
                raise RiskPredictorError(last_error)

            except asyncio.TimeoutError:
                last_error = "Ollama request timed out after 180s"
                logger.warning("Timeout (attempt %d): %s", attempt + 1, last_error)
                if attempt < max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                    logger.info("Retrying in %ds...", delay)
                    await asyncio.sleep(delay)
                    continue
                raise RiskPredictorError(last_error)

            except RiskPredictorError:
                raise

            except Exception as e:
                last_error = f"Ollama risk analysis failed: {e}"
                logger.warning("Error (attempt %d): %s", attempt + 1, last_error)
                if attempt < max_retries - 1:
                    delay = retry_delays[min(attempt, len(retry_delays) - 1)]
                    logger.info("Retrying in %ds...", delay)
                    await asyncio.sleep(delay)
                    continue
                raise RiskPredictorError(last_error)

        raise RiskPredictorError(last_error or "Ollama call failed after retries")

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON response from LLM."""
        if not response:
            raise RiskPredictorError("Empty LLM response")

        response = response.strip()

        if response.startswith("```json"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]

        try:
            parsed = json.loads(response.strip())
            parsed["llm_generated"] = True
            return parsed
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response as JSON: %s\nResponse: %s", e, response[:500])
            return {
                "summary": response[:500],
                "risk_factors": ["LLM response parsing failed"],
                "positive_factors": [],
                "action_items": [],
                "similar_release_analysis": "",
                "probability_reasoning": "",
                "llm_generated": True,
                "parse_error": True,
                "raw_response": response[:1000],
            }

    def _calculate_base_probability(
        self,
        current_metrics: Dict[str, Any],
        historical_avg: Dict[str, Any],
        similar_releases: List[Dict[str, Any]],
        on_time_rate: Dict[str, Any],
        days_to_milestone: int = 0,
    ) -> int:
        """
        Calculate base probability using metrics comparison.
        This provides a starting point that the LLM can then explain.

        Key factors:
        - P0/Blocker bugs are critical blockers
        - P1/Critical bugs need to be resolved before milestones
        - RRS Score reflects overall release readiness
        - Velocity determines if team can resolve issues in time
        """
        base_probability = 70

        p0_bugs = current_metrics.get("p0_bugs", 0)
        p1_bugs = current_metrics.get("p1_bugs", 0)
        total_critical = current_metrics.get("critical_blocker_total", p0_bugs + p1_bugs)
        velocity = current_metrics.get("velocity_per_day", 0)
        rrs_score = current_metrics.get("rrs_score")

        adjustments = 0
        velocity_factor = 0

        # First, calculate velocity-based capacity
        if days_to_milestone > 0 and velocity > 0:
            items_can_resolve = velocity * days_to_milestone
            velocity_ratio = items_can_resolve / total_critical if total_critical > 0 else 10

            if velocity_ratio >= 3:  # Can resolve 3x more than needed
                velocity_factor = 20  # Strong positive
            elif velocity_ratio >= 2:  # Can resolve 2x more than needed
                velocity_factor = 15
            elif velocity_ratio >= 1.5:  # Can resolve 1.5x more than needed
                velocity_factor = 10
            elif velocity_ratio >= 1:  # Can just barely resolve all
                velocity_factor = 0
            elif velocity_ratio >= 0.8:  # Slightly behind
                velocity_factor = -10
            elif velocity_ratio >= 0.5:  # Significantly behind
                velocity_factor = -20
            else:  # Severely behind
                velocity_factor = -30

            logger.info(
                "Velocity ratio: %.1f (can resolve %d, need %d), factor: %+d",
                velocity_ratio,
                items_can_resolve,
                total_critical,
                velocity_factor,
            )

        adjustments += velocity_factor

        # Bug penalties (reduced when velocity can compensate)
        bug_penalty = 0
        if p0_bugs > 0:
            bug_penalty = min(20, p0_bugs * 7)  # Reduced from 10 per bug
            logger.info("P0 bugs penalty: -%d (count: %d)", bug_penalty, p0_bugs)

        if p1_bugs > 10:
            bug_penalty += 15  # Reduced from 20
        elif p1_bugs > 5:
            bug_penalty += 8  # Reduced from 10
        elif p1_bugs > 0:
            bug_penalty += 3  # Reduced from 5

        # If velocity can handle the bugs, reduce penalty
        if velocity_factor >= 10:
            bug_penalty = int(bug_penalty * 0.5)  # Half the penalty if velocity is strong

        adjustments -= bug_penalty

        # RRS score (reduced impact)
        if rrs_score is not None:
            if rrs_score < 50:
                adjustments -= 15  # Reduced from 25
            elif rrs_score < 70:
                adjustments -= 10  # Reduced from 15
            elif rrs_score < 85:
                adjustments -= 5
            elif rrs_score >= 95:
                adjustments += 10

        if on_time_rate.get("available"):
            historical_rate = on_time_rate.get("on_time_rate", 50)
            if historical_rate > 75:
                adjustments += 5
            elif historical_rate < 50:
                adjustments -= 5

        if historical_avg:
            p1_avg = historical_avg.get("p1_bugs", 0)
            if p1_avg > 0 and p1_bugs > p1_avg * 1.5:
                adjustments -= 10
            elif p1_avg > 0 and p1_bugs < p1_avg * 0.5:
                adjustments += 5

            velocity_avg = historical_avg.get("velocity_per_day", 0)
            if velocity_avg > 0:
                if velocity > velocity_avg * 1.2:
                    adjustments += 5
                elif velocity < velocity_avg * 0.7:
                    adjustments -= 10

        if similar_releases:
            on_time_similar = sum(1 for r in similar_releases[:3] if r.get("outcome_data", {}).get("on_time", False))
            total_similar = min(3, len(similar_releases))
            if total_similar > 0:
                similar_rate = on_time_similar / total_similar
                if similar_rate >= 0.67:
                    adjustments += 5
                elif similar_rate <= 0.33:
                    adjustments -= 5

        probability = max(5, min(95, base_probability + adjustments))

        logger.info(
            "Risk probability for metrics (p0=%d, p1=%d, rrs=%s): base=%d, adj=%d, final=%d",
            p0_bugs,
            p1_bugs,
            rrs_score,
            base_probability,
            adjustments,
            probability,
        )

        return int(probability)

    def _determine_risk_level(self, probability: int) -> str:
        """Determine risk level from probability."""
        if probability >= 75:
            return "low"
        elif probability >= 50:
            return "medium"
        else:
            return "high"

    def _get_milestone_criteria(self, milestone: str) -> str:
        """Get the exit criteria for a specific milestone."""
        criteria = {
            "IRR": "Zero P0/Blocker bugs required. P1/Critical bugs should be under 5. Code freeze begins after IRR.",
            "Branch Cut": "Zero P0/Blocker bugs AND zero P1/Critical bugs (or approved waivers). Only approved bug fixes after this.",
            "Final Build": "Zero P0/P1 bugs. Regression tests must pass (>95%). This build goes to production.",
            "Day 1 Deploy": "Production deployment. All prior milestones must be completed successfully.",
        }
        return criteria.get(milestone, "Standard release milestone requirements apply.")

    async def _generate_insights(
        self,
        release_id: str,
        current_metrics: Dict[str, Any],
        historical_avg: Dict[str, Any],
        similar_releases: List[Dict[str, Any]],
        days_to_milestone: int,
        milestone: str,
        base_probability: int,
    ) -> tuple[Dict[str, Any], int]:
        """
        Generate LLM-powered insights using Ollama.

        Returns:
            Tuple of (insights_dict, latency_ms)

        Raises:
            RiskPredictorError if LLM call fails
        """
        p0_bugs = current_metrics.get("p0_bugs", 0)
        p1_bugs = current_metrics.get("p1_bugs", 0)
        total_critical = current_metrics.get("critical_blocker_total", p0_bugs + p1_bugs)
        velocity = current_metrics.get("velocity_per_day", 0)
        rrs_score = current_metrics.get("rrs_score")

        # Calculate projections for the LLM
        items_can_resolve = velocity * days_to_milestone if velocity > 0 else 0
        bugs_remaining_at_milestone = max(0, total_critical - items_can_resolve)
        velocity_needed = total_critical / days_to_milestone if days_to_milestone > 0 else total_critical
        days_needed = total_critical / velocity if velocity > 0 else float("inf")
        buffer_days = days_to_milestone - days_needed if days_needed != float("inf") else 0

        # Calculate late bug risk estimate (historical: 5-10% of open bugs become late P0s)
        open_bugs = current_metrics.get("open_bugs", 0)
        late_bug_estimate_low = int(open_bugs * 0.05)
        late_bug_estimate_high = int(open_bugs * 0.10)

        # Determine if on track based on math
        is_on_track = bugs_remaining_at_milestone == 0 and velocity >= velocity_needed
        track_status = "ON TRACK" if is_on_track else "NOT ON TRACK"

        prompt = f"""Analyze release risk for {release_id}. Your summary MUST include specific numbers.

## CALCULATED METRICS (use these exact numbers):
- **Critical bugs to resolve:** {total_critical}
- **Current velocity:** {velocity:.1f} items/day
- **Days to clear bugs:** {total_critical} ÷ {velocity:.1f} = {days_needed:.1f} days
- **Days available:** {days_to_milestone}
- **Buffer/Deficit:** {buffer_days:.1f} days {'buffer' if buffer_days >= 0 else 'deficit'}
- **Minimum velocity needed:** {total_critical} ÷ {days_to_milestone} = {velocity_needed:.1f} items/day
- **Velocity margin:** {velocity:.1f} - {velocity_needed:.1f} = {velocity - velocity_needed:.1f} items/day {'surplus' if velocity >= velocity_needed else 'deficit'}

## LATE BUG RISK:
- Open bugs (all priorities): {open_bugs}
- Estimated late P0/P1 discoveries: {late_bug_estimate_low}-{late_bug_estimate_high} bugs (5-10% historical rate)
- If {late_bug_estimate_high} late P0s found: buffer drops to {buffer_days - (late_bug_estimate_high / velocity if velocity > 0 else 0):.1f} days

## OTHER DATA:
- RRS Score: {rrs_score}/100
- Open Stories: {current_metrics.get('open_stories', 0)}
- In Code Review: {current_metrics.get('code_review', 0)}
- Test Pass Rate: {current_metrics.get('test_pass_rate', 'UNKNOWN')}{'%' if current_metrics.get('test_pass_rate') else ' (risk: unknown test health)'}

## STATUS: {track_status}
"""
        if similar_releases:
            prompt += "\n## SIMILAR RELEASES:\n"
            for sr in similar_releases[:3]:
                outcome = sr.get("outcome_data", {})
                outcome_str = "on-time" if outcome.get("on_time") else f"slipped {outcome.get('slip_days', '?')} days"
                prompt += f"- {sr['release']}: {outcome_str}\n"

        prompt += f"""
## REQUIRED OUTPUT FORMAT:
Your summary MUST follow this pattern:
"[RISK LEVEL]: {total_critical} bugs ÷ {velocity:.1f}/day = {days_needed:.1f} days to clear, {abs(buffer_days):.1f} days {'buffer' if buffer_days >= 0 else 'deficit'}. [One quantified risk, e.g., '{open_bugs} open bugs may yield {late_bug_estimate_low}-{late_bug_estimate_high} late blockers']."

Do NOT use qualitative phrases like "faces risks from" or "could impact". Use NUMBERS."""

        response, latency_ms = await self._call_llm(prompt)
        insights = self._parse_llm_response(response)

        return insights, latency_ms

    async def predict_risk(
        self,
        release_id: str,
        current_metrics: Dict[str, Any],
        days_to_milestone: int,
        milestone: str,
        phase: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate risk prediction for a release using Ollama LLM.

        Args:
            release_id: Release identifier (e.g., "R136")
            current_metrics: Current release metrics
            days_to_milestone: Days until next milestone
            milestone: Next milestone name (e.g., "IRR", "Branch Cut")
            phase: Optional phase override

        Returns:
            Complete risk prediction with probability, insights, and recommendations

        Raises:
            RiskPredictorError if Ollama is not available or call fails
        """
        if not self._configured:
            raise RiskPredictorError(
                "Ollama LLM not configured. Risk prediction requires Ollama. "
                "Set ADK_LLM_PROVIDER=ollama and configure ADK_OLLAMA_BASE_URL, "
                "ADK_OLLAMA_API_TOKEN, ADK_LLM_MODEL in your .env file."
            )

        if phase is None:
            phase = f"{milestone.lower().replace(' ', '_')}_minus_{days_to_milestone}"
            if days_to_milestone <= 0:
                phase = milestone.lower().replace(" ", "_")

        historical_avg = calculate_historical_averages(phase, exclude_release=release_id)

        similar_releases = get_similar_releases(current_metrics, phase, exclude_release=release_id, limit=3)

        on_time_rate = get_on_time_rate(phase, exclude_release=release_id)

        base_probability = self._calculate_base_probability(
            current_metrics, historical_avg, similar_releases, on_time_rate, days_to_milestone
        )

        risk_level = self._determine_risk_level(base_probability)

        ai_insights, llm_latency_ms = await self._generate_insights(
            release_id,
            current_metrics,
            historical_avg,
            similar_releases,
            days_to_milestone,
            milestone,
            base_probability,
        )

        historical_count = historical_avg.get("releases_compared", 0)
        has_valid_insights = ai_insights and not ai_insights.get("parse_error")

        if historical_count >= 3 and has_valid_insights:
            confidence = "high"
        elif historical_count >= 1 and has_valid_insights:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "release_id": release_id,
            "current_phase": phase,
            "days_to_milestone": days_to_milestone,
            "milestone": milestone,
            "prediction": {
                "probability": base_probability,
                "risk_level": risk_level,
                "confidence": confidence,
            },
            "current_metrics": current_metrics,
            "historical_average": historical_avg,
            "similar_releases": [
                {
                    "release": sr["release"],
                    "similarity": sr["similarity"],
                    "outcome": sr["outcome"],
                }
                for sr in similar_releases
            ],
            "on_time_rate": on_time_rate,
            "ai_insights": ai_insights,
            "generated_at": datetime.now().isoformat(),
            "llm_model": self._model,
            "llm_latency_ms": llm_latency_ms,
            "llm_available": True,
        }

    async def is_available(self) -> Dict[str, Any]:
        """Check if Ollama LLM is available and responding."""
        status = {
            "available": self._configured,
            "llm_configured": self._configured,
            "llm_backend": "ollama" if self._configured else None,
            "llm_model": self._model if self._configured else None,
            "llm_base_url": self._base_url if self._configured else None,
        }

        if not self._configured:
            status["error"] = (
                "Ollama not configured. Set ADK_LLM_PROVIDER=ollama, "
                "ADK_OLLAMA_BASE_URL, ADK_OLLAMA_API_TOKEN, ADK_LLM_MODEL"
            )
            return status

        try:
            start_time = time.time()
            headers = _get_auth_headers(self._api_token, self._auth_mode)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    latency_ms = int((time.time() - start_time) * 1000)
                    status["llm_reachable"] = resp.status == 200
                    status["health_check_latency_ms"] = latency_ms
                    status["auth_mode"] = self._auth_mode

                    if resp.status == 200:
                        data = await resp.json()
                        status["available_models"] = [m.get("id") for m in data.get("data", [])]
                    else:
                        status["error"] = f"Health check returned status {resp.status}"

        except aiohttp.ClientConnectorError as e:
            status["llm_reachable"] = False
            status["error"] = f"Cannot connect to Ollama: {e}"
        except Exception as e:
            status["llm_reachable"] = False
            status["error"] = str(e)

        return status


_risk_predictor: Optional[RiskPredictor] = None


def get_risk_predictor() -> RiskPredictor:
    """Get singleton risk predictor instance."""
    global _risk_predictor
    if _risk_predictor is None:
        _risk_predictor = RiskPredictor()
    return _risk_predictor
