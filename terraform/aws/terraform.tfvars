# Current desired state for the AWS stack.
# A pull request that edits this file changes cloud cost, and the FinOps gate
# compares the plan on this branch against the plan on the base branch.
instance_type       = "m5.xlarge"
instance_count      = 2
root_volume_size_gb = 100
data_volume_count   = 2
data_volume_size_gb = 500
enable_nat_gateway  = true
