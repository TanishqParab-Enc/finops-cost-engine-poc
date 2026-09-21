terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Centralised multi-cloud state: the Terraform backend is independent of the
  # cloud being deployed, so this GCP workload stores state in the SAME S3
  # bucket the AWS accelerator uses. No GCS backend is created for this POC.
  # Resolves to finops-poc/dev/gcp/sandbox/terraform.tfstate.
  backend "s3" {}
}
