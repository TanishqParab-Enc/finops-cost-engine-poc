terraform {
  # Matches the rest of the repository (see terraform/workloads/web-platform).
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Backend config is supplied at init time via -backend-config flags by the
  # shared FinOps pipeline, which reads bucket/key from the stack registry
  # (config/finops-stacks.yml). Empty here on purpose so this workload keeps
  # its own state at finops-poc/dev/ecommerce-platform/terraform.tfstate and
  # never shares state with any other workload. Local runs:
  # `terraform init -backend=false` to skip state.
  backend "s3" {}
}
