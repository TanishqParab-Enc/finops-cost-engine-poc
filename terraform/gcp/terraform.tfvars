# Current desired state for the GCP stack.
# A pull request that edits this file changes cloud cost, and the FinOps gate
# compares the plan on this branch against the plan on the base branch.
machine_type      = "e2-medium"
instance_count    = 1
boot_disk_size_gb = 20
boot_disk_type    = "pd-balanced"
data_disk_count   = 0
enable_static_ip  = false
