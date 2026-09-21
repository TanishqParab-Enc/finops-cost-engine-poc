output "multicloud_state_role_arn" {
  description = "Set as the AWS_MULTICLOUD_STATE_ROLE_ARN repository secret."
  value       = aws_iam_role.multicloud_state.arn
}

output "multicloud_state_role_name" {
  value = aws_iam_role.multicloud_state.name
}

output "managed_state_prefixes" {
  description = "The only state key prefixes this role can reach."
  value       = local.managed_state_prefixes
}
