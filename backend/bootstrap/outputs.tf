output "state_bucket_name" {
  description = "Name of the Terraform state bucket. Use this in each environment's backend.hcl."
  value       = module.terraform_state.bucket_id
}

output "state_bucket_arn" {
  description = "ARN of the Terraform state bucket."
  value       = module.terraform_state.bucket_arn
}

output "state_bucket_region" {
  description = "Region of the Terraform state bucket."
  value       = module.terraform_state.bucket_region
}

output "aws_account_id" {
  description = "AWS account the state bucket was created in."
  value       = data.aws_caller_identity.current.account_id
}

output "legacy_dynamodb_table_name" {
  description = "Deprecated DynamoDB lock table name, if one was created."
  value       = module.terraform_state.legacy_dynamodb_table_name
}

output "next_steps" {
  description = "What to do after bootstrap completes."
  value       = <<-EOT
    Bootstrap complete.

    1. Copy the bucket name into each environment's backend.hcl:
         bucket = "${module.terraform_state.bucket_id}"
    2. cd ../environments/dev
    3. cp backend.hcl.example backend.hcl
    4. cp terraform.tfvars.example terraform.tfvars   # then edit it
    5. terraform init -backend-config=backend.hcl
    6. terraform plan -var-file=terraform.tfvars
  EOT
}
