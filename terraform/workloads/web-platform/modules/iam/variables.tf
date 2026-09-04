variable "name_prefix" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "assets_bucket_arn" {
  type = string
}

variable "log_group_arn" {
  type = string
}
