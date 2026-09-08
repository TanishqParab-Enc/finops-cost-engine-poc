variable "name_prefix" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "retention_days" {
  type = number
}

variable "autoscaling_group_name" {
  type = string
}
