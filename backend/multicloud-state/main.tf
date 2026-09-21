# Dedicated AWS state-only role for Azure/GCP Terraform runs.
#
# WHY THIS EXISTS
# Azure and GCP workloads deploy to their own clouds but keep Terraform state
# in the SAME S3 bucket the AWS accelerator already uses. That means an
# Azure/GCP workflow needs TWO independent identities in one job:
#
#   AWS OIDC role (this one) -> Terraform state/locking in S3, nothing else
#   Azure/GCP identity       -> the actual resource deployment
#
# The existing finops-poc-dev-deploy-role is intentionally Action="*" for the
# AWS POC and must NOT be reused here - that would hand every Azure/GCP run
# full AWS account access purely to read a state file.
#
# ISOLATION
# This root is deliberately standalone (like backend/bootstrap). It reads the
# already-provisioned OIDC provider as a data source and creates exactly one
# role. It does not modify, import or reference any existing backend module,
# environment or role, so applying it cannot regress the validated AWS layer.

terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70.0, < 7.0.0"
    }
  }

  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "Terraform"
      Purpose   = "Multi-cloud Terraform state access"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# The provider is already deployed by the AWS backend layer. Reading it keeps
# this root from creating a second one (only one per issuer URL is allowed).
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

locals {
  account_id       = data.aws_caller_identity.current.account_id
  partition        = data.aws_partition.current.partition
  state_bucket_arn = "arn:${local.partition}:s3:::${var.state_bucket_name}"

  role_name = "${var.project_name}-multicloud-state-role"

  # Same dual-form subject handling the AWS roles already use: GitHub emits an
  # "immutable" subject embedding numeric IDs on this repo, so both forms are
  # trusted or the role silently stops being assumable.
  repo_classic = "${var.github_owner}/${var.github_repository}"
  repo_immutable = (
    var.github_owner_id != null && var.github_repository_id != null
    ? "${var.github_owner}@${var.github_owner_id}/${var.github_repository}@${var.github_repository_id}"
    : null
  )
  repo_forms = compact([local.repo_classic, local.repo_immutable])

  # Deployment jobs run inside a GitHub Environment; cost-gate/plan jobs run on
  # a pull request or a trusted branch. Both need state access, so both subject
  # shapes are trusted - but nothing wildcard.
  trusted_subjects = flatten([
    for repo in local.repo_forms : concat(
      ["repo:${repo}:pull_request"],
      [for b in var.allowed_branches : "repo:${repo}:ref:refs/heads/${b}"],
      [for e in var.github_environments : "repo:${repo}:environment:${e}"],
    )
  ])

  # Only the non-AWS prefixes. The AWS workloads keep using their own roles, so
  # this role is structurally unable to touch AWS workload state.
  managed_state_prefixes = flatten([
    for env in var.environments : [
      for cloud in var.managed_clouds : "finops-poc/${env}/${cloud}/*"
    ]
  ])
}

data "aws_iam_policy_document" "trust" {
  statement {
    sid     = "GitHubOidcAssume"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.trusted_subjects
    }
  }
}

data "aws_iam_policy_document" "state_access" {
  # ListBucket is a BUCKET-level action, so the resource is the bucket itself
  # and the prefix restriction has to come from a condition. Without this
  # condition the role could enumerate every key in the bucket, including the
  # AWS workloads' and the backend layer's own state.
  statement {
    sid       = "ListOnlyMulticloudPrefixes"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = local.managed_state_prefixes
    }
  }

  # PutObject/DeleteObject are required even for a read-only plan: S3 native
  # locking (use_lockfile=true) writes and then removes a .tflock object
  # alongside the state object.
  statement {
    sid    = "ReadWriteMulticloudStateObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = [for prefix in local.managed_state_prefixes : "${local.state_bucket_arn}/${prefix}"]
  }

  # ---------------------------------------------------------------------
  # Explicit fences. The Allow statements above already grant nothing else,
  # but these make the boundary auditable and keep it true even if a future
  # managed policy is ever attached to this role by mistake. Deny wins.
  # ---------------------------------------------------------------------
  statement {
    sid     = "DenyAwsWorkloadAndBackendState"
    effect  = "Deny"
    actions = ["s3:*"]

    # s3:prefix is only present on bucket-level calls. On object calls the key
    # is absent, and an absent key under StringNotLike evaluates TRUE - which
    # would deny this role's own state objects. The boundary is therefore
    # expressed as NotResource, which needs no request-context key at all.
    # The bucket ARN is excluded so ListBucket stays governed by its own
    # prefix-conditioned Allow above.
    not_resources = concat(
      [for prefix in local.managed_state_prefixes : "${local.state_bucket_arn}/${prefix}"],
      [local.state_bucket_arn],
    )
  }

  statement {
    sid    = "DenyStateBucketReconfiguration"
    effect = "Deny"
    actions = [
      "s3:DeleteBucket",
      "s3:PutBucketPolicy",
      "s3:DeleteBucketPolicy",
      "s3:PutBucketVersioning",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutEncryptionConfiguration",
      "s3:PutBucketAcl",
      "s3:PutBucketOwnershipControls",
      "s3:PutLifecycleConfiguration",
    ]
    resources = [local.state_bucket_arn]
  }

  # This role must never become a deployment or privilege-management identity.
  statement {
    sid       = "DenyIdentityAndTrustManagement"
    effect    = "Deny"
    actions   = ["iam:*", "sts:AssumeRole"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "multicloud_state" {
  name                 = local.role_name
  description          = "Terraform state/lock access in S3 for Azure and GCP workloads. No AWS deployment rights."
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "multicloud_state" {
  name   = "${local.role_name}-s3-state"
  role   = aws_iam_role.multicloud_state.id
  policy = data.aws_iam_policy_document.state_access.json
}
