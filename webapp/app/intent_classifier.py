"""Intent classification for planner questions using OpenVINO Qwen.

This module provides a small, testable wrapper around ``openvino_genai.LLMPipeline``
and returns strongly-typed Pydantic output.
"""

from __future__ import annotations

import json
import os
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class IntentLabel(str, Enum):
    InventoryLookup = "InventoryLookup"
    ForecastLookup = "ForecastLookup"
    PurchaseOrderLookup = "PurchaseOrderLookup"
    RiskAnalysis = "RiskAnalysis"
    KPIAnalysis = "KPIAnalysis"
    CustomerOrderLookup = "CustomerOrderLookup"
    Other = "Other"


class IntentClassificationResult(BaseModel):
    classification_result: IntentLabel
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1)


class OpenVINOQwenIntentClassifier:
    """Classifies user queries into IFSP intent labels with confidence and reasoning."""

    def __init__(self, model_path: str | None = None, device: str | None = None):
        self.model_path = model_path or os.getenv("OPENVINO_QWEN_MODEL_PATH") or os.getenv("OPENVINO_MODEL_PATH")
        self.device = device or os.getenv("OPENVINO_DEVICE", "GPU")
        self._pipeline = None

    def _load_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        if not self.model_path:
            raise ValueError("OpenVINO Qwen model path is not set. Configure OPENVINO_QWEN_MODEL_PATH or OPENVINO_MODEL_PATH.")
        import openvino_genai as ov_genai

        perf_hint = os.getenv("OPENVINO_PERFORMANCE_HINT", "LATENCY")
        self._pipeline = ov_genai.LLMPipeline(self.model_path, self.device, {"PERFORMANCE_HINT": perf_hint})
        return self._pipeline

    def classify(self, query: str) -> IntentClassificationResult:
        if not query or not query.strip():
            return IntentClassificationResult(
                classification_result=IntentLabel.Other,
                confidence_score=0.0,
                reasoning="Empty query provided.",
            )

        pipeline = self._load_pipeline()
        prompt = self._build_prompt(query)
        raw = pipeline.generate(prompt, max_new_tokens=220, temperature=0.0, do_sample=False)
        return self._parse_model_output(raw)

    @staticmethod
    def _build_prompt(query: str) -> str:
        return (
            "You are an intent classification engine for supply planning queries.\n"
            "Classify the user query into exactly one label from:\n"
            "- InventoryLookup\n"
            "- ForecastLookup\n"
            "- PurchaseOrderLookup\n"
            "- RiskAnalysis\n"
            "- KPIAnalysis\n"
            "- CustomerOrderLookup\n"
            "- Other\n\n"
            "Return strict JSON only with keys:\n"
            "classification_result, confidence_score, reasoning\n"
            "Where confidence_score is a float between 0 and 1.\n\n"
            f"Query: {query}\n"
        )

    @classmethod
    def _parse_model_output(cls, raw_text: str) -> IntentClassificationResult:
        payload = cls._extract_json_payload(raw_text)
        if payload is None:
            return IntentClassificationResult(
                classification_result=IntentLabel.Other,
                confidence_score=0.2,
                reasoning="Model output was not valid JSON for intent classification.",
            )

        normalized = cls._normalize_payload(payload)
        return IntentClassificationResult.model_validate(normalized)

    @staticmethod
    def _extract_json_payload(raw_text: str) -> dict[str, Any] | None:
        text = (raw_text or "").strip()
        if not text:
            return None

        text = text.replace("```json", "").replace("```", "").strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Attempt light cleanup for trailing commas.
            candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        label = str(result.get("classification_result", "Other")).strip()
        if label not in {e.value for e in IntentLabel}:
            label = "Other"
        result["classification_result"] = label

        score = result.get("confidence_score", 0.2)
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.2
        score = max(0.0, min(1.0, score))
        result["confidence_score"] = score

        reasoning = str(result.get("reasoning", "Classification completed.")).strip()
        if not reasoning:
            reasoning = "Classification completed."
        result["reasoning"] = reasoning
        return result


__all__ = [
    "IntentLabel",
    "IntentClassificationResult",
    "OpenVINOQwenIntentClassifier",
]
