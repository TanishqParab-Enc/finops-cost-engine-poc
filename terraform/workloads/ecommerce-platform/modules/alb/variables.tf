variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "vpc_id" {
  description = "VPC the target group registers instances in."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets the load balancer is attached to."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group allowing public HTTP ingress."
  type        = string
}
