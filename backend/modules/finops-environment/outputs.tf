output "plan_role_arn" {
  description = "ARN of the GitHub Actions plan role."
  value       = module.github_actions_roles.plan_role_arn
}

output "deploy_role_arn" {
  description = "ARN of the GitHub Actions deploy role."
  value       = module.github_actions_roles.deploy_role_arn
}

output "github_oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider in use."
  value       = module.github_oidc.provider_arn
}

output "oidc_provider_created_here" {
  description = "True when this environment created the OIDC provider."
  value       = module.github_oidc.was_created
}

output "terraform_state_bucket" {
  description = "Terraform state bucket backing this environment."
  value       = var.state_bucket_name
}

output "terraform_state_key" {
  description = "State object key for this environment."
  value       = "${var.project_name}/${var.environment}/terraform.tfstate"
}

output "github_environment_name" {
  description = "GitHub Actions environment gating deployments."
  value       = var.github_environment_name
}

output "plan_trust_subjects" {
  description = "OIDC subjects permitted to assume the plan role."
  value       = module.github_actions_roles.plan_trust_subjects
}

output "deploy_trust_subjects" {
  description = "OIDC subjects permitted to assume the deploy role."
  value       = module.github_actions_roles.deploy_trust_subjects
}

output "bedrock_policy_arn" {
  description = "ARN of the scoped Bedrock invoke policy, if enabled."
  value       = module.github_actions_roles.bedrock_policy_arn
}
