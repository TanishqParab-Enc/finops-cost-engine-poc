terraform {
  # 1.10+ matches the rest of the repository (see terraform/aws/main.tf).
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Backend config is supplied at init time via -backend-config flags in CI
  # (see the `deploy` job in .github/workflows/finops-cost-gate.yml), the same
  # pattern terraform/aws/main.tf uses. Empty here on purpose. Local runs:
  # `terraform init -backend=false` to skip state.
  # State key: finops-poc/dev/web-platform/terraform.tfstate (bucket finops-poc-tfstate-024125831628).
  backend "s3" {}
}
