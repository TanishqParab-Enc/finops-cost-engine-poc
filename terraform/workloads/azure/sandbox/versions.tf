terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  # Centralised multi-cloud state: the Terraform backend is independent of the
  # cloud being deployed, so this Azure workload stores state in the SAME S3
  # bucket the AWS accelerator uses. Configured entirely at init time via
  # -backend-config so the key can never drift from the registry's state_key.
  # Resolves to finops-poc/dev/azure/sandbox/terraform.tfstate.
  backend "s3" {}
}
