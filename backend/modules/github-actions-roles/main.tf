# GitHub Actions IAM roles: separate plan (read) and deploy (write) identities.
#
# Trust is scoped to a single GitHub repository and to explicit subject
# patterns, never `sub = "*"`.

data "aws_partition" "current" {}

locals {
  name_prefix = "${var.project_name}-${var.environment}"

  plan_role_name   = coalesce(var.plan_role_name, "${local.name_prefix}-plan-role")
  deploy_role_name = coalesce(var.deploy_role_name, "${local.name_prefix}-deploy-role")

  repo = "${var.github_owner}/${var.github_repository}"

  # Pull requests from the repo, plus pushes to the allowed branches.
  plan_subjects = length(var.plan_subjects) > 0 ? var.plan_subjects : concat(
    ["repo:${local.repo}:pull_request"],
    [for b in var.allowed_branches : "repo:${local.repo}:ref:refs/heads/${b}"],
  )

  # Deployment is only permitted from the protected GitHub environment, so the
  # environment's required reviewers gate every use of this role.
  deploy_subjects = length(var.deploy_subjects) > 0 ? var.deploy_subjects : [
    "repo:${local.repo}:environment:${var.github_environment_name}",
  ]

  state_bucket_arn = "arn:${data.aws_partition.current.partition}:s3:::${var.state_bucket_name}"

  tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
      Purpose     = "GitHub Actions OIDC role"
    },
    var.tags,
  )
}

# ---------------------------------------------------------------------------
# Trust policies
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "plan_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.plan_subjects
    }
  }
}

data "aws_iam_policy_document" "deploy_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.deploy_subjects
    }
  }
}

# ---------------------------------------------------------------------------
# Terraform state access (both roles need it; plan writes the lock file)
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "state_access" {
  statement {
    sid       = "ListStateBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]
  }

  # s3:PutObject/DeleteObject are required even for `plan` because native S3
  # locking (use_lockfile) writes and removes a .tflock object.
  statement {
    sid    = "ReadWriteStateObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = [for prefix in var.state_key_prefixes : "${local.state_bucket_arn}/${prefix}"]
  }
}

resource "aws_iam_policy" "state_access" {
  name        = "${local.name_prefix}-tfstate-access"
  description = "Read/write Terraform state objects and the S3 native lock file."
  policy      = data.aws_iam_policy_document.state_access.json
  tags        = local.tags
}

# ---------------------------------------------------------------------------
# Bedrock access for the AI explanation layer (plan role only).
#
# The application invokes a cross-region inference profile. Per AWS docs, when
# an inference profile is named in Resource you must ALSO grant the underlying
# foundation model in EVERY region the profile routes to. The condition key
# restricts foundation-model access to calls made through this profile only.
# Regions confirmed 2026-09-02 via `aws bedrock get-inference-profile`.
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "bedrock" {
  count = var.enable_bedrock_access ? 1 : 0

  statement {
    sid       = "InvokeInferenceProfile"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = [var.bedrock_inference_profile_arn]
  }

  statement {
    sid       = "InvokeFoundationModelsViaProfileOnly"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = var.bedrock_foundation_model_arns

    condition {
      test     = "StringLike"
      variable = "bedrock:InferenceProfileArn"
      values   = [var.bedrock_inference_profile_arn]
    }
  }
}

resource "aws_iam_policy" "bedrock" {
  count = var.enable_bedrock_access ? 1 : 0

  name        = "${local.name_prefix}-bedrock-invoke"
  description = "Invoke only the configured Bedrock inference profile used by the FinOps AI explanation layer."
  policy      = data.aws_iam_policy_document.bedrock[0].json
  tags        = local.tags
}

# ---------------------------------------------------------------------------
# Plan role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "plan" {
  name                 = local.plan_role_name
  description          = "GitHub Actions role for terraform plan and FinOps cost analysis. Read-only on infrastructure."
  assume_role_policy   = data.aws_iam_policy_document.plan_trust.json
  max_session_duration = var.max_session_duration
  tags                 = merge(local.tags, { Role = "plan" })
}

resource "aws_iam_role_policy" "plan_read" {
  name   = "${local.name_prefix}-plan-read"
  role   = aws_iam_role.plan.id
  policy = var.plan_read_policy_json
}

resource "aws_iam_role_policy_attachment" "plan_state" {
  role       = aws_iam_role.plan.name
  policy_arn = aws_iam_policy.state_access.arn
}

resource "aws_iam_role_policy_attachment" "plan_bedrock" {
  count = var.enable_bedrock_access ? 1 : 0

  role       = aws_iam_role.plan.name
  policy_arn = aws_iam_policy.bedrock[0].arn
}

resource "aws_iam_role_policy_attachment" "plan_additional" {
  for_each = toset(var.plan_additional_policy_arns)

  role       = aws_iam_role.plan.name
  policy_arn = each.value
}

# ---------------------------------------------------------------------------
# Deploy role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "deploy" {
  name                 = local.deploy_role_name
  description          = "GitHub Actions role for terraform apply. Used only from the protected GitHub environment."
  assume_role_policy   = data.aws_iam_policy_document.deploy_trust.json
  max_session_duration = var.max_session_duration
  tags                 = merge(local.tags, { Role = "deploy" })
}

resource "aws_iam_role_policy" "deploy_write" {
  name   = "${local.name_prefix}-deploy-write"
  role   = aws_iam_role.deploy.id
  policy = var.deploy_write_policy_json
}

resource "aws_iam_role_policy_attachment" "deploy_state" {
  role       = aws_iam_role.deploy.name
  policy_arn = aws_iam_policy.state_access.arn
}

resource "aws_iam_role_policy_attachment" "deploy_additional" {
  for_each = toset(var.deploy_additional_policy_arns)

  role       = aws_iam_role.deploy.name
  policy_arn = each.value
}
