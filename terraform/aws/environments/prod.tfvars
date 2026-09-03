# PROD workload deployment sizing.
#
# Deliberately distinct from BOTH PR test-scenario values - not PR #3's
# m5.large/50 GB, not PR #4's m5.xlarge x2/100 GB/2x500 GB/NAT - so this file
# is never mistaken for test scaffolding. One step up from dev.tfvars
# (t3.small, slightly larger root volume) for a POC-scale production
# workload; still no data volumes or NAT gateway, since neither is exercised
# by the current module beyond count = 0/false. Revisit before a real launch.
#
# Explicitly sets every declared variable (not just the ones terraform.tfvars
# happens to set today), using variables.tf's existing defaults for ami_id/
# data_volume_size_gb/service. This makes the file self-contained: a future
# edit to terraform.tfvars (the gate-baseline file, meant to be edited by
# PRs) can never be silently inherited by a real deploy.
region              = "us-east-1"
environment         = "Prod"
service             = "finops-poc"
ami_id              = "ami-0c02fb55956c7d316"
instance_type       = "t3.small"
instance_count      = 1
root_volume_size_gb = 30
data_volume_count   = 0
data_volume_size_gb = 100
enable_nat_gateway  = false
