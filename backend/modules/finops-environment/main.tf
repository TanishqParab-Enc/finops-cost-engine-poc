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

# Default AWS-managed keys the workload's RDS instance uses when it doesn't
# specify its own kms_key_id/master_user_secret_kms_key_id. Referenced by ARN
# (not alias) below so the grant is scoped to these two specific keys rather
# than "*", per the narrowest-fix requirement - no customer CMK is created,
# and none of the default key's own policy needs to change.
data "aws_kms_key" "workload_rds_default" {
  count  = length(local.workload_prefixes) > 0 ? 1 : 0
  key_id = "alias/aws/rds"
}

data "aws_kms_key" "workload_secretsmanager_default" {
  count  = length(local.workload_prefixes) > 0 ? 1 : 0
  key_id = "alias/aws/secretsmanager"
}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  # Registered workloads that TURN ON the generic workload-management
  # statements below (ManageWorkloadInstanceRole, ManageWorkloadAssetBucket,
  # ManageWorkloadDataServices, ...). No longer used to SCOPE those
  # statements - their resources are "*" so any registered workload is
  # covered without a corresponding IAM change here.
  workload_prefixes = compact(concat([var.workload_name_prefix], var.additional_workload_name_prefixes))

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

  # The GitHub Actions environment names backend.yml actually uses for the
  # other environment (dev/production - "staging" was dropped 2026-09-03: it
  # shared dev's role/trust anyway and added no real isolation), so the
  # shared deploy role's trust also covers it. Kept as a fixed list rather
  # than derived from var.environment, since "prod" maps to the GitHub
  # environment "production", not "prod".
  all_backend_github_environments   = ["dev", "production"]
  other_backend_github_environments = setsubtract(local.all_backend_github_environments, [var.github_environment_name])

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
# extra_plan_actions as the POC grows. The deploy role's own write access is
# no longer extended this way - see DeployAnyWorkloadResource below.
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

  # terraform plan also evaluates aws_kms_key data sources (see
  # modules/database/main.tf), so the plan role needs read-only access to the
  # same two keys the deploy role can act on - describe only, never
  # decrypt/grant, which stay deploy-time-only permissions.
  dynamic "statement" {
    for_each = var.workload_name_prefix != "" ? [1] : []

    content {
      sid     = "ReadWorkloadDefaultKmsKeysForPlan"
      effect  = "Allow"
      actions = ["kms:DescribeKey"]
      resources = [
        data.aws_kms_key.workload_rds_default[0].arn,
        data.aws_kms_key.workload_secretsmanager_default[0].arn,
      ]
    }
  }
}

data "aws_iam_policy_document" "deploy_write" {
  # ---------------------------------------------------------------------
  # POC DESIGN DECISION (2026-09-16): full administrative deployment access.
  #
  # This is deliberately NOT a least-privilege production IAM design. The
  # requirement is that a FUTURE Terraform codebase using ANY AWS service can
  # be onboarded without editing this file, which an explicit action catalog
  # can never guarantee - IAM is an allow-list, so an unlisted service is a
  # denied service. Every bounded per-service statement that used to live
  # here (compute, networking, S3, RDS, ElastiCache, CloudFront/Route 53,
  # SQS, Secrets Manager, KMS, and the Auto Scaling/ELB/RDS/ElastiCache
  # service-linked-role grants) is subsumed by this one statement, including
  # every Create/Read/Update/Delete/Tag/Attach/Detach/Replace/PassRole/
  # CreateServiceLinkedRole call Terraform makes for any service.
  #
  # The blast radius is bounded NOT by this statement's actions but by:
  #   1. the Deny statements below, which fence off the FinOps control plane
  #      (both CI roles, the GitHub OIDC provider, the Terraform state
  #      bucket) so this role can never rewrite what governs it;
  #   2. the OIDC trust policy, which only lets GitHub Actions assume this
  #      role from the trusted repo/branch/environment;
  #   3. the FinOps gate itself - plan, Infracost, the deterministic cost
  #      policy and the approval environment all run BEFORE any apply, and
  #      the apply consumes the saved plan rather than re-planning.
  #
  # The previous design's aws:RequestedRegion confinement is intentionally
  # dropped here: a future workload may be multi-region, and re-adding the
  # condition would reintroduce exactly the per-workload IAM edits this
  # change exists to eliminate.
  # ---------------------------------------------------------------------
  dynamic "statement" {
    for_each = length(local.workload_prefixes) > 0 ? [1] : []

    content {
      sid       = "DeployAnyWorkloadResource"
      effect    = "Allow"
      actions   = ["*"]
      resources = ["*"]
    }
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
        # The AWS provider checks for instance profiles before deleting a
        # role; missing this makes `terraform destroy` fail on DeleteRole
        # after already removing the role's policies. Confirmed for real on
        # 2026-09-03.
        "iam:ListInstanceProfilesForRole",
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

  # ---------------------------------------------------------------------
  # FinOps control-plane boundary.
  #
  # DeployAnyWorkloadResource above grants Action="*" / Resource="*", so
  # these Deny statements - not the Allow list - are what actually stops this
  # role rewriting the governance that constrains it. Deny always wins over
  # Allow. Unlike the Allow statements they are deliberately NOT gated on
  # enable_backend_self_management: the full-access grant applies regardless
  # of that flag, so the fence has to as well, otherwise disabling backend
  # self-management would remove the fence while leaving Action="*" in place.
  # ---------------------------------------------------------------------

  # Every mutating IAM call against either CI role, expressed as "everything
  # except reads" rather than a fixed action list: under Action="*" a fixed
  # list silently fails open the day AWS ships a new IAM write action, which
  # is exactly the failure mode this boundary must not have. Get*/List* stay
  # allowed so plan/apply can still refresh the backend layer's own state.
  statement {
    sid    = "DenySelfPrivilegeEscalation"
    effect = "Deny"

    not_actions = [
      "iam:Get*",
      "iam:List*",
    ]

    resources = [
      "arn:${local.partition}:iam::${local.account_id}:role/${local.deploy_role_name}",
      "arn:${local.partition}:iam::${local.account_id}:role/${local.plan_role_name}",
    ]
  }

  # The OIDC provider IS the authentication boundary - deleting it or
  # retargeting its thumbprint/audience would let a different repository
  # assume these roles. This deliberately supersedes ManageGitHubOidcProvider
  # above; legitimate OIDC changes run through the privileged human/local
  # path, which is a different principal and so unaffected by this Deny.
  statement {
    sid    = "DenyGitHubOidcTrustTampering"
    effect = "Deny"
    actions = [
      "iam:DeleteOpenIDConnectProvider",
      "iam:UpdateOpenIDConnectProviderThumbprint",
      "iam:AddClientIDToOpenIDConnectProvider",
      "iam:RemoveClientIDFromOpenIDConnectProvider",
    ]
    resources = [
      "arn:${local.partition}:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com",
    ]
  }

  # The state bucket holds every stack's Terraform state and the cost-lock
  # evidence the gate reads. Bucket-level destruction and the settings that
  # protect it are denied. Object-level access is deliberately NOT denied:
  # Terraform must still read/write state objects and create/delete the
  # .tflock object that S3 native locking (use_lockfile) depends on.
  statement {
    sid    = "DenyStateBucketTampering"
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
    ]
    resources = [
      "arn:${local.partition}:s3:::${var.state_bucket_name}",
    ]
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
  additional_deploy_environments = (
    var.enable_backend_self_management ? local.other_backend_github_environments : []
  )
  allowed_branches = var.allowed_branches

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
