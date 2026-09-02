terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70.0, < 7.0.0"
    }
  }

  # Partial configuration - supply via: terraform init -backend-config=backend.hcl
  # Uses S3 native locking (use_lockfile), not the deprecated DynamoDB table.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region
}

module "backend" {
  source = "../../modules/finops-environment"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  github_owner            = var.github_owner
  github_repository       = var.github_repository
  github_owner_id         = var.github_owner_id
  github_repository_id    = var.github_repository_id
  github_environment_name = var.github_environment_name
  allowed_branches        = var.allowed_branches

  # Only one OIDC provider may exist per AWS account. The first environment
  # applied creates it; the others reuse it via existing_oidc_provider_arn.
  create_oidc_provider       = var.create_oidc_provider
  existing_oidc_provider_arn = var.existing_oidc_provider_arn

  state_bucket_name = var.state_bucket_name

  enable_bedrock_access         = var.enable_bedrock_access
  bedrock_model_id              = var.bedrock_model_id
  bedrock_inference_profile_arn = var.bedrock_inference_profile_arn
  bedrock_foundation_model_arns = var.bedrock_foundation_model_arns

  extra_plan_actions   = var.extra_plan_actions
  extra_deploy_actions = var.extra_deploy_actions

  tags = var.tags
}
