variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "noncurrent_expiration_days" {
  description = "Days before a superseded object version is deleted."
  type        = number
}

variable "ia_transition_days" {
  description = "Days before an object moves to Standard-IA."
  type        = number
}
