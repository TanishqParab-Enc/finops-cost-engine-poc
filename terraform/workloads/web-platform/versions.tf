terraform {
  # 1.10+ matches the rest of the repository (see terraform/aws/main.tf).
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Deliberately no backend block. This workload exists to exercise the FinOps
  # gate against a realistic resource mix; it is never deployed, so it must not
  # be able to touch any live state.
}
