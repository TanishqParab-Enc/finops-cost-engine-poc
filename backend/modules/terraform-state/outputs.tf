output "bucket_id" {
  description = "Name of the Terraform state S3 bucket."
  value       = aws_s3_bucket.state.id
}

output "bucket_arn" {
  description = "ARN of the Terraform state S3 bucket."
  value       = aws_s3_bucket.state.arn
}

output "bucket_region" {
  description = "Region the state bucket resides in."
  value       = aws_s3_bucket.state.region
}

output "legacy_dynamodb_table_name" {
  description = "Name of the deprecated DynamoDB lock table, if one was created."
  value       = try(aws_dynamodb_table.legacy_lock[0].name, null)
}

output "legacy_dynamodb_table_arn" {
  description = "ARN of the deprecated DynamoDB lock table, if one was created."
  value       = try(aws_dynamodb_table.legacy_lock[0].arn, null)
}
