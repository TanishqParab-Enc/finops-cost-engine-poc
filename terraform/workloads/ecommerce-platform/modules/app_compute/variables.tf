variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "ami_id" {
  description = "AMI for storefront instances."
  type        = string
}

variable "instance_type" {
  description = "Storefront instance type."
  type        = string
}

variable "instance_profile_name" {
  description = "Instance profile granting the storefront tier its least-privilege role."
  type        = string
}

variable "security_group_id" {
  description = "Security group allowing ingress only from the load balancer."
  type        = string
}

variable "app_subnet_ids" {
  description = "Private application subnets the group spreads instances across."
  type        = list(string)
}

variable "target_group_arn" {
  description = "Target group instances register with."
  type        = string
}

variable "desired_capacity" {
  description = "Steady-state instance count."
  type        = number
}

variable "min_capacity" {
  description = "Minimum instance count."
  type        = number
}

variable "max_capacity" {
  description = "Maximum instance count."
  type        = number
}

variable "root_volume_size" {
  description = "Root EBS volume size in GiB."
  type        = number
}

variable "root_volume_type" {
  description = "Root EBS volume type."
  type        = string
}

variable "cpu_target_percent" {
  description = "Average CPU the target-tracking policy holds."
  type        = number
  default     = 60
}
