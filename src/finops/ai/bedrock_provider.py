"""AWS Bedrock provider — Claude via the same OIDC credentials used for Terraform.

No extra secrets needed: the GitHub Actions OIDC role that runs `terraform plan`
also calls `bedrock:InvokeModel` once the policy in Phase A includes it.

Default model: Claude 3 Haiku (fast, cheap, excellent JSON output).
Override with FINOPS_BEDROCK_MODEL env var.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..errors import AIError
from .base import AIProvider

DEFAULT_MODEL = "anthropic.claude-3-haiku-20240307-v1:0"
DEFAULT_REGION = "us-east-1"


class BedrockProvider(AIProvider):
    name = "bedrock"

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.model_id = os.environ.get("FINOPS_BEDROCK_MODEL") or DEFAULT_MODEL
        self.region = os.environ.get("FINOPS_BEDROCK_REGION") or DEFAULT_REGION
        self.timeout_seconds = timeout_seconds

    def _client(self):
        try:
            import boto3
        except ImportError as exc:
            raise AIError(
                "boto3 is not installed",
                detail="Run: pip install 'finops-cost-engine[bedrock]'",
            ) from exc
        try:
            return boto3.client(
                "bedrock-runtime",
                region_name=self.region,
                config=_boto_config(self.timeout_seconds),
            )
        except Exception as exc:  # noqa: BLE001
            raise AIError("Could not create Bedrock client", detail=str(exc)) from exc

    def analyze_raw(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "temperature": 0.2,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
        )
        try:
            response = self._client().invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
        except Exception as exc:  # noqa: BLE001
            raise AIError("Bedrock invoke_model failed", detail=str(exc)) from exc

        try:
            raw = json.loads(response["body"].read())
            content = raw["content"][0]["text"]
            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AIError("Unexpected Bedrock response shape", detail=str(exc)) from exc


def _boto_config(timeout_seconds: int):
    try:
        from botocore.config import Config

        return Config(
            connect_timeout=min(timeout_seconds, 10),
            read_timeout=timeout_seconds,
            retries={"max_attempts": 2},
        )
    except ImportError:
        return None
