# Current desired state for the Azure stack.
# A pull request that edits this file changes cloud cost, and the FinOps gate
# compares the plan on this branch against the plan on the base branch.
vm_size          = "Standard_B1s"
instance_count   = 1
os_disk_type     = "StandardSSD_LRS"
os_disk_size_gb  = 32
data_disk_count  = 0
enable_public_ip = false
