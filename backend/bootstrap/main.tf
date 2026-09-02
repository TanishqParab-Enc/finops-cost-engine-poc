# Bootstrap: creates the S3 bucket that every other layer uses as its backend.
#
# This layer runs on LOCAL state by design - Terraform cannot store state in a
# bucket that does not exist yet. It is applied once per AWS account and is
# intentionally minimal so it rarely needs to change.
#
#   terraform init
#   terraform apply -var-file=terraform.tfvars
#
# The resulting local terraform.tfstate is gitignored. Back it up, or import the
# bucket later if it is lost - the bucket itself is protected by prevent_destroy.

terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70.0, < 7.0.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "Terraform"
      Layer     = "bootstrap"
    }
  }
}

data "aws_caller_identity" "current" {}

module "terraform_state" {
  source = "../modules/terraform-state"

  project_name   = var.project_name
  aws_account_id = data.aws_caller_identity.current.account_id
  bucket_name    = var.state_bucket_name

  noncurrent_version_retention_days = var.noncurrent_version_retention_days

  # Deprecated; only enable when migrating a pre-1.10 backend.
  enable_legacy_dynamodb_lock = var.enable_legacy_dynamodb_lock

  tags = {
    Purpose = "Terraform remote state for all finops-poc environments"
  }
}
