# GitHub Actions environments, protection rules and non-secret variables.
#
# Separate state and lifecycle from the AWS layers on purpose:
#   * AWS provisioning never needs a GitHub token
#   * a GitHub misconfiguration cannot corrupt AWS state
#   * this layer is optional; the same result can be achieved with `gh` CLI
#
# Secrets are NOT managed here. Anything set through the GitHub provider is
# stored in plaintext in Terraform state, so tokens are set out-of-band:
#   gh secret set INFRACOST_API_KEY --repo <owner>/<repo>
#
# Requires a GITHUB_TOKEN environment variable with `repo` scope (plus
# `admin:org` if using team reviewers).

terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    github = {
      source  = "integrations/github"
      version = ">= 6.2.0, < 7.0.0"
    }
  }

  backend "s3" {}
}

provider "github" {
  owner = var.github_owner
}

module "environments" {
  source   = "../modules/github-environment"
  for_each = var.environments

  github_repository = var.github_repository
  environment_name  = each.key

  reviewer_user_ids   = each.value.reviewer_user_ids
  reviewer_team_ids   = each.value.reviewer_team_ids
  prevent_self_review = each.value.prevent_self_review
  wait_timer_minutes  = each.value.wait_timer_minutes

  restrict_deployment_branches = each.value.restrict_deployment_branches
  only_protected_branches      = each.value.only_protected_branches
  deployment_branch_patterns   = each.value.deployment_branch_patterns

  environment_variables = each.value.variables

  # Repository-level variables are global, so only set them once.
  repository_variables = each.key == var.primary_environment ? var.repository_variables : {}
}
