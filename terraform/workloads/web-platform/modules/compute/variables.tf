variable "name_prefix" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "ami_id" {
  type = string
}

variable "instance_type" {
  type = string
}

variable "instance_profile_name" {
  type = string
}

variable "security_group_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "target_group_arn" {
  type = string
}

variable "desired_capacity" {
  type = number
}

variable "min_capacity" {
  type = number
}

variable "max_capacity" {
  type = number
}

variable "root_volume_size" {
  type = number
}

variable "root_volume_type" {
  type = string
}
