"""Unit tests for config loading, sanitisation, change detection and AI schema."""

from __future__ import annotations

from decimal import Decimal

import pytest

from finops.ai.schema import validate_analysis
from finops.ai.json_extract import extract_json_object
from finops.config import load_config
from finops.errors import AIError, ConfigurationError
from finops.plan.detector import classify_files
from finops.plan.sanitizer import REDACTED, sanitize_attributes, sanitize_plan

from ..conftest import make_config

pytestmark = pytest.mark.unit

POLICY_YAML = """
schema_version: "1.0"
threshold:
  metric: incremental_monthly_cost
  value: 250
  currency: USD
evaluation:
  equality_is_pass: true
cost_estimation:
  estimator: infracost
fail_safe:
  on_estimation_failure: BLOCK
"""


class TestConfigLoading:
    def test_loads_repo_policy_file(self):
        config = load_config("config/finops-policy.yaml")
        assert config.threshold.metric == "incremental_monthly_cost"
        assert config.cost_estimation.estimator == "infracost"
        assert config.cost_estimation.allow_non_authoritative_lock is False

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ConfigurationError, match="not found"):
            load_config(tmp_path / "nope.yaml")

    def test_reads_threshold_from_file(self, tmp_path):
        path = tmp_path / "p.yaml"
        path.write_text(POLICY_YAML, encoding="utf-8")
        assert load_config(path).threshold.value == Decimal("250")

    def test_env_overrides_file(self, tmp_path, monkeypatch):
        path = tmp_path / "p.yaml"
        path.write_text(POLICY_YAML, encoding="utf-8")
        monkeypatch.setenv("FINOPS_THRESHOLD_VALUE", "42")
        monkeypatch.setenv("FINOPS_THRESHOLD_METRIC", "incremental_annual_cost")
        config = load_config(path)
        assert config.threshold.value == Decimal("42")
        assert config.threshold.metric == "incremental_annual_cost"

    def test_rejects_unknown_metric(self, tmp_path, monkeypatch):
        path = tmp_path / "p.yaml"
        path.write_text(POLICY_YAML, encoding="utf-8")
        monkeypatch.setenv("FINOPS_THRESHOLD_METRIC", "made_up")
        with pytest.raises(ConfigurationError, match="Unknown threshold.metric"):
            load_config(path)

    def test_rejects_negative_threshold(self, tmp_path, monkeypatch):
        path = tmp_path / "p.yaml"
        path.write_text(POLICY_YAML, encoding="utf-8")
        monkeypatch.setenv("FINOPS_THRESHOLD_VALUE", "-5")
        with pytest.raises(ConfigurationError, match=">= 0"):
            load_config(path)

    def test_rejects_non_numeric_threshold(self, tmp_path, monkeypatch):
        path = tmp_path / "p.yaml"
        path.write_text(POLICY_YAML, encoding="utf-8")
        monkeypatch.setenv("FINOPS_THRESHOLD_VALUE", "lots")
        with pytest.raises(ConfigurationError, match="numeric"):
            load_config(path)

    def test_rejects_bad_failsafe_action(self, tmp_path):
        path = tmp_path / "p.yaml"
        path.write_text(POLICY_YAML.replace("BLOCK", "MAYBE"), encoding="utf-8")
        with pytest.raises(ConfigurationError, match="BLOCK or WARN"):
            load_config(path)

    def test_rejects_invalid_yaml(self, tmp_path):
        path = tmp_path / "p.yaml"
        path.write_text("threshold: [unclosed", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="parse"):
            load_config(path)


class TestChangeDetection:
    def setup_method(self):
        self.cd = make_config().change_detection

    def test_detects_terraform_files(self):
        result = classify_files(["terraform/aws/main.tf", "README.md"], self.cd)
        assert result.has_infrastructure_changes
        assert result.infrastructure_files == ["terraform/aws/main.tf"]

    def test_detects_tfvars(self):
        assert classify_files(["terraform/aws/scenarios/pass.tfvars"], self.cd).has_infrastructure_changes

    def test_root_level_tf_file_matches(self):
        assert classify_files(["main.tf"], self.cd).has_infrastructure_changes

    def test_ignores_terraform_cache(self):
        result = classify_files([".terraform/providers/x.tf"], self.cd)
        assert not result.has_infrastructure_changes

    def test_no_infra_changes_for_docs_only_pr(self):
        result = classify_files(["README.md", "docs/ARCHITECTURE.md", "src/app.py"], self.cd)
        assert not result.has_infrastructure_changes
        assert len(result.other_files) == 3


class TestSanitizer:
    def test_allowlists_cost_relevant_attributes_only(self):
        result = sanitize_attributes(
            {"instance_type": "m5.large", "ami": "ami-123", "private_ip": "10.0.0.1"}
        )
        assert result == {"instance_type": "m5.large"}

    def test_sensitive_key_outside_allowlist_is_dropped_entirely(self):
        assert "kms_key" not in sanitize_attributes({"kms_key": "arn:aws:kms:secret"})

    def test_redacts_sensitive_keys_nested_inside_allowed_structures(self):
        result = sanitize_attributes(
            {"root_block_device": [{"volume_size": 50, "kms_key_id": "arn:aws:kms:secret"}]}
        )
        block = result["root_block_device"][0]
        assert block["volume_size"] == 50
        assert block["kms_key_id"] == REDACTED

    @pytest.mark.parametrize(
        "key", ["password", "admin_password", "client_secret", "api_key", "user_data", "private_key"]
    )
    def test_sensitive_keys_never_pass_through(self, key):
        assert key not in sanitize_attributes({key: "s3cr3t", "instance_type": "m5.large"})

    def test_truncates_long_strings(self):
        assert len(sanitize_attributes({"sku_name": "x" * 500})["sku_name"]) == 200

    def test_limits_list_length(self):
        result = sanitize_attributes({"ebs_block_device": [{"volume_size": i} for i in range(20)]})
        assert len(result["ebs_block_device"]) == 5

    def test_plan_summary_truncation_flag(self, plans_dir):
        from finops.plan.normalizer import normalize_plan_file

        plan = normalize_plan_file(plans_dir / "aws-fail.json")
        payload = sanitize_plan(plan, max_resources=1)
        assert payload["truncated"] is True
        assert len(payload["changes"]) == 1

    def test_no_secret_material_reaches_ai_payload(self, plans_dir):
        from finops.plan.normalizer import normalize_plan_file

        plan = normalize_plan_file(plans_dir / "azure-fail.json")
        blob = str(sanitize_plan(plan)).lower()
        for banned in ("ssh-rsa", "client_secret", "admin_password", "private_key"):
            assert banned not in blob


class TestAISchema:
    def test_accepts_valid_payload(self):
        payload = {
            "summary": "s",
            "reason": "r",
            "cost_drivers": ["a"],
            "recommendation": "rec",
        }
        assert validate_analysis(payload) == payload

    def test_rejects_missing_field(self):
        with pytest.raises(AIError, match="schema validation"):
            validate_analysis({"summary": "s", "reason": "r", "cost_drivers": []})

    def test_rejects_non_object(self):
        with pytest.raises(AIError, match="not a JSON object"):
            validate_analysis("hello")

    def test_rejects_extra_properties_such_as_model_supplied_cost(self):
        with pytest.raises(AIError, match="schema validation"):
            validate_analysis(
                {
                    "summary": "s",
                    "reason": "r",
                    "cost_drivers": [],
                    "recommendation": "r",
                    "cost_impact": 999999,
                }
            )


class TestJsonExtraction:
    """Claude via Bedrock wraps JSON in a markdown fence even when told not to
    (confirmed against a real Bedrock call on 2026-09-02); every provider must
    tolerate this.
    """

    def test_plain_json_object(self):
        assert extract_json_object('{"a": 1}') == {"a": 1}

    def test_markdown_fenced_json(self):
        text = '```json\n{"a": 1, "b": "two"}\n```'
        assert extract_json_object(text) == {"a": 1, "b": "two"}

    def test_fenced_without_language_tag(self):
        text = '```\n{"a": 1}\n```'
        assert extract_json_object(text) == {"a": 1}

    def test_json_surrounded_by_prose(self):
        text = 'Here is the result:\n{"a": 1}\nHope that helps!'
        assert extract_json_object(text) == {"a": 1}

    def test_leading_trailing_whitespace(self):
        assert extract_json_object('  \n{"a": 1}\n  ') == {"a": 1}

    def test_raises_on_non_json_text(self):
        with pytest.raises(AIError, match="did not return valid JSON"):
            extract_json_object("not json at all")

    def test_raises_on_json_array_not_object(self):
        with pytest.raises(AIError):
            extract_json_object("[1, 2, 3]")
