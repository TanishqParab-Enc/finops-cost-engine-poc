# Composes the AWS side of the backend for a single environment.
#
# Every environment (dev/staging/prod/qa/...) calls this module with different
# inputs, so module logic exists in exactly one place.
#
# GitHub environments/variables are managed separately in backend/github so
# that AWS provisioning never requires a GitHub token, and so the two have
# independent state and lifecycles.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  # Each environment gets its own state key namespace.
  state_key_prefixes = [
    "${var.project_name}/${var.environment}/*",
  ]

  common_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    },
    var.tags,
  )
}

# ---------------------------------------------------------------------------
# Least-privilege policies for the POC's Terraform resources.
#
# The POC provisions aws_instance, aws_ebs_volume and aws_nat_gateway. Actions
# are listed explicitly so the blast radius is obvious in review; extend via
# extra_plan_actions / extra_deploy_actions as the POC grows.
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "plan_read" {
  # terraform plan refreshes state, which requires Describe on every managed
  # resource type. Describe* actions do not support resource-level scoping.
  statement {
    sid    = "DescribeInfrastructureForPlan"
    effect = "Allow"
    actions = concat([
      "ec2:DescribeInstances",
      "ec2:DescribeInstanceAttribute",
      "ec2:DescribeInstanceTypes",
      "ec2:DescribeInstanceCreditSpecifications",
      "ec2:DescribeVolumes",
      "ec2:DescribeVolumeAttribute",
      "ec2:DescribeNatGateways",
      "ec2:DescribeAddresses",
      "ec2:DescribeSubnets",
      "ec2:DescribeVpcs",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeImages",
      "ec2:DescribeAvailabilityZones",
      "ec2:DescribeTags",
    ], var.extra_plan_actions)
    resources = ["*"]
  }

  # Identity check performed by the AWS provider on startup.
  statement {
    sid       = "ProviderIdentityCheck"
    effect    = "Allow"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "deploy_write" {
  statement {
    sid    = "ManagePocCompute"
    effect = "Allow"
    actions = concat([
      "ec2:RunInstances",
      "ec2:TerminateInstances",
      "ec2:StartInstances",
      "ec2:StopInstances",
      "ec2:ModifyInstanceAttribute",
      "ec2:CreateVolume",
      "ec2:DeleteVolume",
      "ec2:AttachVolume",
      "ec2:DetachVolume",
      "ec2:ModifyVolume",
      "ec2:CreateNatGateway",
      "ec2:DeleteNatGateway",
      "ec2:AllocateAddress",
      "ec2:ReleaseAddress",
      "ec2:CreateTags",
      "ec2:DeleteTags",
    ], var.extra_deploy_actions)
    resources = ["*"]

    # Confine writes to this region; the POC is single-region.
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.aws_region]
    }
  }

  # Apply also refreshes state, so it needs the same read actions.
  statement {
    sid       = "DescribeInfrastructureForApply"
    effect    = "Allow"
    actions   = ["ec2:Describe*", "sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

# ---------------------------------------------------------------------------
# OIDC provider
# ---------------------------------------------------------------------------
module "github_oidc" {
  source = "../github-oidc"

  project_name          = var.project_name
  create_provider       = var.create_oidc_provider
  existing_provider_arn = var.existing_oidc_provider_arn
  tags                  = local.common_tags
}

# ---------------------------------------------------------------------------
# IAM roles
# ---------------------------------------------------------------------------
module "github_actions_roles" {
  source = "../github-actions-roles"

  project_name = var.project_name
  environment  = var.environment

  oidc_provider_arn = module.github_oidc.provider_arn

  github_owner            = var.github_owner
  github_repository       = var.github_repository
  github_owner_id         = var.github_owner_id
  github_repository_id    = var.github_repository_id
  github_environment_name = var.github_environment_name
  allowed_branches        = var.allowed_branches

  state_bucket_name  = var.state_bucket_name
  state_key_prefixes = local.state_key_prefixes

  plan_read_policy_json    = data.aws_iam_policy_document.plan_read.json
  deploy_write_policy_json = data.aws_iam_policy_document.deploy_write.json

  plan_role_name   = var.plan_role_name
  deploy_role_name = var.deploy_role_name

  enable_bedrock_access         = var.enable_bedrock_access
  bedrock_inference_profile_arn = var.bedrock_inference_profile_arn
  bedrock_foundation_model_arns = var.bedrock_foundation_model_arns

  tags = local.common_tags
}
