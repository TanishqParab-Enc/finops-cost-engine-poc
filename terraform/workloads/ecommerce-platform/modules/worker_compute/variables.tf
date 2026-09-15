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
  description = "AMI for worker instances."
  type        = string
}

variable "instance_type" {
  description = "Worker instance type."
  type        = string
}

variable "instance_profile_name" {
  description = "Instance profile granting the worker tier its least-privilege role."
  type        = string
}

variable "security_group_id" {
  description = "Security group with no inbound rules."
  type        = string
}

variable "app_subnet_ids" {
  description = "Private application subnets the group spreads instances across."
  type        = list(string)
}

variable "desired_capacity" {
  description = "Steady-state worker count."
  type        = number
}

variable "min_capacity" {
  description = "Minimum worker count."
  type        = number
}

variable "max_capacity" {
  description = "Maximum worker count."
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

variable "queue_name" {
  description = "Order queue the scaling policy measures backlog on."
  type        = string
}

variable "backlog_target_per_instance" {
  description = "Visible messages per worker the scaling policy holds."
  type        = number
  default     = 20
}
