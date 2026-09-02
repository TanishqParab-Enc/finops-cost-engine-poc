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

  # Must match the names github-actions-roles derives, so the anti-escalation
  # Deny below targets the right role ARNs.
  plan_role_name   = coalesce(var.plan_role_name, "${var.project_name}-${var.environment}-plan-role")
  deploy_role_name = coalesce(var.deploy_role_name, "${var.project_name}-${var.environment}-deploy-role")

  # AWS_PLAN_ROLE_ARN/AWS_DEPLOY_ROLE_ARN are single repo-level secrets shared
  # by every environment's CI job, so in practice ONE role pair manages every
  # environment's backend state, not one pair per environment. State access
  # must therefore span the whole project when self-management is enabled -
  # scoping it to just this environment's prefix denies every other
  # environment's plan/apply with "not authorized to perform s3:PutObject",
  # confirmed for real on 2026-09-02 (Plan (staging) using dev's role).
  # IAM management is already project-wide (see the *_iam_write statements
  # below), so this keeps the two consistent instead of a half-measure that
  # blocks bootstrapping sibling environments.
  state_key_prefixes = (
    var.enable_backend_self_management
    ? ["${var.project_name}/*"]
    : ["${var.project_name}/${var.environment}/*"]
  )

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

  # The backend layer manages IAM roles, policies and the OIDC provider, so
  # planning it needs to read them. Read-only, and IAM Get/List actions do not
  # support resource-level conditions for all of these.
  dynamic "statement" {
    for_each = var.enable_backend_self_management ? [1] : []

    content {
      sid    = "ReadBackendIamForPlan"
      effect = "Allow"
      actions = [
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies",
        "iam:ListRoleTags",
        "iam:GetPolicy",
        "iam:GetPolicyVersion",
        "iam:ListPolicyVersions",
        "iam:ListPolicyTags",
        "iam:GetOpenIDConnectProvider",
        "iam:ListOpenIDConnectProviders",
      ]
      resources = ["*"]
    }
  }

  dynamic "statement" {
    for_each = var.enable_backend_self_management ? [1] : []

    content {
      sid    = "ReadStateBucketConfigForPlan"
      effect = "Allow"
      actions = [
        "s3:GetBucketVersioning",
        "s3:GetBucketPolicy",
        "s3:GetBucketAcl",
        "s3:GetBucketTagging",
        "s3:GetBucketLocation",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketOwnershipControls",
        "s3:GetEncryptionConfiguration",
        "s3:GetLifecycleConfiguration",
      ]
      resources = ["arn:${local.partition}:s3:::${var.state_bucket_name}"]
    }
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

  # ---------------------------------------------------------------------
  # Backend self-management.
  #
  # SECURITY: a principal that can write IAM can escalate to administrator.
  # This is scoped to resources carrying the project prefix, and the explicit
  # Deny below stops the deploy role rewriting its own trust policy or the
  # plan role's. Set enable_backend_self_management = false to run the backend
  # layer only from a human workstation.
  # ---------------------------------------------------------------------
  dynamic "statement" {
    for_each = var.enable_backend_self_management ? [1] : []

    content {
      sid    = "ManageBackendIamRead"
      effect = "Allow"
      actions = [
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies",
        "iam:ListRoleTags",
        "iam:GetPolicy",
        "iam:GetPolicyVersion",
        "iam:ListPolicyVersions",
        "iam:ListPolicyTags",
        "iam:GetOpenIDConnectProvider",
        "iam:ListOpenIDConnectProviders",
      ]
      resources = ["*"]
    }
  }

  dynamic "statement" {
    for_each = var.enable_backend_self_management ? [1] : []

    content {
      sid    = "ManageBackendIamWrite"
      effect = "Allow"
      actions = [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:UpdateRole",
        "iam:UpdateRoleDescription",
        "iam:UpdateAssumeRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:CreatePolicy",
        "iam:DeletePolicy",
        "iam:CreatePolicyVersion",
        "iam:DeletePolicyVersion",
        "iam:TagPolicy",
        "iam:UntagPolicy",
      ]
      resources = [
        "arn:${local.partition}:iam::${local.account_id}:role/${var.project_name}-*",
        "arn:${local.partition}:iam::${local.account_id}:policy/${var.project_name}-*",
      ]
    }
  }

  # The OIDC provider ARN is fixed by its issuer URL and cannot be prefixed.
  dynamic "statement" {
    for_each = var.enable_backend_self_management ? [1] : []

    content {
      sid    = "ManageGitHubOidcProvider"
      effect = "Allow"
      actions = [
        "iam:CreateOpenIDConnectProvider",
        "iam:DeleteOpenIDConnectProvider",
        "iam:UpdateOpenIDConnectProviderThumbprint",
        "iam:AddClientIDToOpenIDConnectProvider",
        "iam:RemoveClientIDFromOpenIDConnectProvider",
        "iam:TagOpenIDConnectProvider",
        "iam:UntagOpenIDConnectProvider",
      ]
      resources = [
        "arn:${local.partition}:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com",
      ]
    }
  }

  # Prevents the deploy role from granting itself more privilege, or from
  # disabling the plan role. Deny always wins over Allow.
  dynamic "statement" {
    for_each = var.enable_backend_self_management ? [1] : []

    content {
      sid    = "DenySelfPrivilegeEscalation"
      effect = "Deny"
      actions = [
        "iam:UpdateAssumeRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:DeleteRole",
      ]
      resources = [
        "arn:${local.partition}:iam::${local.account_id}:role/${local.deploy_role_name}",
        "arn:${local.partition}:iam::${local.account_id}:role/${local.plan_role_name}",
      ]
    }
  }

  dynamic "statement" {
    for_each = var.enable_backend_self_management ? [1] : []

    content {
      sid    = "ManageStateBucketConfig"
      effect = "Allow"
      actions = [
        "s3:CreateBucket",
        "s3:GetBucket*",
        "s3:PutBucket*",
        "s3:GetEncryptionConfiguration",
        "s3:PutEncryptionConfiguration",
        "s3:GetLifecycleConfiguration",
        "s3:PutLifecycleConfiguration",
      ]
      resources = ["arn:${local.partition}:s3:::${var.state_bucket_name}"]
    }
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
