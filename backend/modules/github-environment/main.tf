# GitHub Actions environment, protection rules and non-secret variables.
#
# Deliberately does NOT manage the Infracost token. Any secret set through the
# GitHub provider is stored in plaintext in Terraform state, so tokens are set
# out-of-band with `gh secret set` (see backend/README.md).

locals {
  manage_reviewers = length(var.reviewer_user_ids) > 0 || length(var.reviewer_team_ids) > 0
}

resource "github_repository_environment" "this" {
  repository  = var.github_repository
  environment = var.environment_name

  # GitHub rejects self-review only when reviewers are configured.
  prevent_self_review = local.manage_reviewers ? var.prevent_self_review : null

  wait_timer = var.wait_timer_minutes

  dynamic "reviewers" {
    for_each = local.manage_reviewers ? [1] : []

    content {
      users = var.reviewer_user_ids
      teams = var.reviewer_team_ids
    }
  }

  dynamic "deployment_branch_policy" {
    for_each = var.restrict_deployment_branches ? [1] : []

    content {
      protected_branches     = var.only_protected_branches
      custom_branch_policies = !var.only_protected_branches
    }
  }
}

resource "github_repository_environment_deployment_policy" "branches" {
  for_each = var.restrict_deployment_branches && !var.only_protected_branches ? toset(var.deployment_branch_patterns) : toset([])

  repository     = var.github_repository
  environment    = github_repository_environment.this.environment
  branch_pattern = each.value
}

# Non-secret configuration consumed by the workflow.
resource "github_actions_environment_variable" "this" {
  for_each = var.environment_variables

  repository    = var.github_repository
  environment   = github_repository_environment.this.environment
  variable_name = each.key
  value         = each.value
}

resource "github_actions_variable" "repository" {
  for_each = var.repository_variables

  repository    = var.github_repository
  variable_name = each.key
  value         = each.value
}
