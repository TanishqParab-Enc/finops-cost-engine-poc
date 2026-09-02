output "plan_role_arn" {
  description = "ARN of the GitHub Actions plan role."
  value       = aws_iam_role.plan.arn
}

output "plan_role_name" {
  description = "Name of the GitHub Actions plan role."
  value       = aws_iam_role.plan.name
}

output "deploy_role_arn" {
  description = "ARN of the GitHub Actions deploy role."
  value       = aws_iam_role.deploy.arn
}

output "deploy_role_name" {
  description = "Name of the GitHub Actions deploy role."
  value       = aws_iam_role.deploy.name
}

output "plan_trust_subjects" {
  description = "OIDC subject claims permitted to assume the plan role."
  value       = local.plan_subjects
}

output "deploy_trust_subjects" {
  description = "OIDC subject claims permitted to assume the deploy role."
  value       = local.deploy_subjects
}

output "bedrock_policy_arn" {
  description = "ARN of the scoped Bedrock invoke policy, if enabled."
  value       = try(aws_iam_policy.bedrock[0].arn, null)
}
