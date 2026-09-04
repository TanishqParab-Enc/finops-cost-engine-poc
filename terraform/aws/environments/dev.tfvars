# DEV workload deployment sizing.
#
# Deliberately mirrors the existing gate-baseline shape (t3.micro / 20 GB, no
# extras) rather than PR #3's test-scenario values (m5.large / 50 GB) - this
# file is what a real `deploy_environment: dev` run applies, not a test
# fixture, so it stays at the cheapest sizing the module supports.
#
# Explicitly sets every declared variable (not just the ones terraform.tfvars
# happens to set today), using variables.tf's existing defaults for ami_id/
# data_volume_size_gb/service. This makes the file self-contained: a future
# edit to terraform.tfvars (the gate-baseline file, meant to be edited by
# PRs) can never be silently inherited by a real deploy.
region              = "us-east-1"
environment         = "Dev"
service             = "finops-poc"
ami_id              = "ami-0c02fb55956c7d316"
instance_type       = "m5.4xlarge"
instance_count      = 1
root_volume_size_gb = 20
data_volume_count   = 0
data_volume_size_gb = 100
enable_nat_gateway  = false
