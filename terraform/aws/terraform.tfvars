# Current desired state for the AWS stack.
# A pull request that edits this file changes cloud cost, and the FinOps gate
# compares the plan on this branch against the plan on the base branch.
instance_type       = "m5.large"
instance_count      = 1
root_volume_size_gb = 50
data_volume_count   = 0
enable_nat_gateway  = false
