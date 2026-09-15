output "bucket_id" {
  description = "Product-asset bucket name."
  value       = aws_s3_bucket.assets.id
}

output "bucket_arn" {
  description = "Product-asset bucket ARN, used to scope the tier IAM policies."
  value       = aws_s3_bucket.assets.arn
}

output "bucket_regional_domain_name" {
  description = "Regional domain name used as the CloudFront origin."
  value       = aws_s3_bucket.assets.bucket_regional_domain_name
}
