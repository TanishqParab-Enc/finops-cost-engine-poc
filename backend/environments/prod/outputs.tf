output "terraform_state_bucket" {
  description = "Terraform state bucket backing this environment."
  value       = module.backend.terraform_state_bucket
}

output "terraform_state_key" {
  description = "State object key for this environment."
  value       = module.backend.terraform_state_key
}

output "plan_role_arn" {
  description = "Set as the AWS_PLAN_ROLE_ARN secret/variable in GitHub."
  value       = module.backend.plan_role_arn
}

output "deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN secret/variable in GitHub."
  value       = module.backend.deploy_role_arn
}

output "github_oidc_provider_arn" {
  description = "OIDC provider ARN. Pass to other environments as existing_oidc_provider_arn."
  value       = module.backend.github_oidc_provider_arn
}

output "github_environment_name" {
  description = "GitHub Actions environment gating deployments."
  value       = module.backend.github_environment_name
}

output "plan_trust_subjects" {
  description = "OIDC subjects permitted to assume the plan role."
  value       = module.backend.plan_trust_subjects
}

output "deploy_trust_subjects" {
  description = "OIDC subjects permitted to assume the deploy role."
  value       = module.backend.deploy_trust_subjects
}
