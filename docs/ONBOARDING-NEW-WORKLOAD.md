# Onboarding a new Terraform workload

How to bring another Terraform codebase under this FinOps gate, once the
shared backend (`backend/`) is already provisioned for the target AWS
account. This assumes the new workload lives **in this same repository**
and the **same AWS account** the backend already controls. See
[Different GitHub repository](#different-github-repository) and
[Different AWS account](#different-aws-account) at the end if not.

## Prerequisites

- The shared FinOps backend is already provisioned for the target AWS
  account/environment (`backend/bootstrap` → `backend/environments/<env>`
  already applied) — state bucket, GitHub OIDC provider, plan role, deploy
  role, and the full-access `DeployAnyWorkloadResource` design already live.
- You can push to (or open a PR against) this repository, and the target
  GitHub Environment (e.g. `dev`) already exists with its intended
  protection rules.
- `terraform`, `python`, and the `finops` CLI (`pip install -e ".[dev]"`)
  are available locally for validation — deployment itself always runs
  through the pipeline, never a local `terraform apply`.

## What "onboarding" actually requires

The pipelines (`.github/workflows/finops-cost-gate.yml`,
`terraform-test-destroy.yml`) and the Python engine (`src/finops/`) are
stack-agnostic — they read every stack from one registry file,
[config/finops-stacks.yml](../config/finops-stacks.yml). Onboarding a new
workload in this repo/account means exactly two things:

1. Add the Terraform code under `terraform/workloads/<name>/`.
2. Register it in `config/finops-stacks.yml`.

That's it. **No workload-specific IAM permissions need to be added** to the
shared deploy role for this — see [Why no IAM step](#why-no-iam-step-is-needed)
below. This is the one thing that changed since the original bounded-catalog
design: registering a workload used to also mean iteratively patching
`backend/modules/finops-environment/main.tf` every time the workload used an
AWS service nothing else had used yet (this happened twice for
`ecommerce-platform`: `iam:CreateServiceLinkedRole` for ElastiCache, then
`s3:DeleteBucketPolicy` on destroy — both historical, both resolved by the
current full-access design, see [Why no IAM step](#why-no-iam-step-is-needed)).
That per-service IAM-patching step no longer exists as part of onboarding.

## Same repository, same AWS account

This is the default case this document walks through (Steps 1-9 below):

- Add the Terraform workload under `terraform/workloads/<name>/`.
- Register it in `config/finops-stacks.yml`.
- Reuse the existing shared backend, plan/deploy roles and workflows as-is.
- No new workload-specific IAM grant is required.

## Step 1 — Add the Terraform root

Create `terraform/workloads/<name>/` with its own `main.tf`, `variables.tf`,
`terraform.tfvars`, `provider.tf`, `versions.tf`. Give every resource a
distinct name prefix (e.g. `shopfront-dev-*`) so it never collides with
another workload's resources.

If it has any consumption-priced resources (S3, CloudFront, SQS, CloudWatch,
data transfer, etc.), add an `infracost-usage.yml` next to it — Terraform
alone cannot price usage-based billing, and without this file those
resources price at **zero**, silently understating the bill.

## Step 2 — Register it in `config/finops-stacks.yml`

```yaml
stacks:
  <name>:
    terraform_dir: terraform/workloads/<name>
    cloud: aws
    deployable: true          # start false if you want price/report only, no apply
    environment: dev
    state_key: finops-poc/dev/<name>/terraform.tfstate
    var_file: null
    usage_file: terraform/workloads/<name>/infracost-usage.yml   # omit if none
    paths:
      - terraform/workloads/<name>/
```

| Field | Purpose |
|---|---|
| `terraform_dir` | The Terraform root to plan and apply |
| `deployable` | `false` → priced and reported, but can never mint a cost lock or be applied |
| `environment` | The GitHub Environment (and its protection rules) the deploy runs in |
| `state_key` | The exact remote state object baselined **and** applied |
| `usage_file` | Infracost usage assumptions for consumption-priced resources (omit if none) |
| `paths` | Changed-file prefixes that select this stack on a pull request |

That's the entire pipeline-side change — the gate, the approval flow, the
reporting, and the destroy workflow all resolve stacks from this file alone.

To make it destroyable through `terraform-test-destroy.yml`, also add
`<name>` to that workflow's `workflow_dispatch.inputs.stack.options` list —
its own resolution logic is already generic.

## Step 3 — Validate Terraform

```powershell
terraform fmt -check -recursive
terraform init -backend=false   # from terraform/workloads/<name>
terraform validate
```

## Step 4 — Run the FinOps Cost Gate (dry run first)

```powershell
gh workflow run "FinOps Cost Gate" --ref main -f stack=<name> -f environment=dev -f apply=false
```

This plans, prices, and reports without touching AWS. Confirm the cost
breakdown looks right (right resources, right sizes, no unexpectedly-zero
consumption-priced items) before ever setting `apply=true`.

## Step 5 — Review Infracost and the FinOps decision

The run reports `current monthly cost`, `projected monthly cost`,
`incremental monthly cost`, the configured threshold
(`incremental_monthly_cost`, POC default **$100/month**), and the resulting
`finops_decision` (`PASS` or `BLOCK`). See the main
[README](../README.md#the-threshold) for the exact policy.

## Step 6 — Approve if the cost is `BLOCK`ed

A `BLOCK` pauses the run on the `finops-cost-approval` GitHub Environment.
Review the run, then **Review deployments → Approve/Reject**. Approving sets
`deployment_authorization = AUTHORIZED`; it never rewrites `finops_decision`
from `BLOCK` to `PASS` — those are deliberately separate signals (see the
main [README](../README.md#approval-and-deployment-authorization)).

## Step 7 — Deploy

With `apply=true` (or on an approved/authorized PR), the same run's `deploy`
job applies the **exact saved plan** using the shared deploy role via GitHub
OIDC. No local `terraform apply` is needed or expected.

## Step 8 — Validate outputs

Confirm the run's `Terraform apply` step succeeded and check
`terraform state list` against the workload's `state_key` if you want to
verify resources directly.

## Step 9 — Destroy when done

Use [.github/workflows/terraform-test-destroy.yml](../.github/workflows/terraform-test-destroy.yml)
(`workflow_dispatch`, pick the stack from the registry-backed dropdown, type
`DESTROY` to confirm). It runs a fresh destroy plan, gates it behind the
separate `finops-destroy-approval` Environment, applies through the same
shared deploy role, and finishes with a read-only verification step. No
manual AWS resource deletion is required or expected.

## Why no IAM step is needed

The shared DEV deploy role's policy includes `DeployAnyWorkloadResource`
(`Effect = Allow`, `Action = "*"`, `Resource = "*"`) — a deliberate POC
trade-off so a new workload's AWS services never require a corresponding
backend IAM change. This is bounded by explicit `Deny` statements
(`DenySelfPrivilegeEscalation`, `DenyGitHubOidcTrustTampering`,
`DenyStateBucketTampering`) that protect the FinOps control plane itself —
see the main [README](../README.md#security) for exactly what those do and
don't prevent. It does **not** bypass the FinOps gate, approval, OIDC
authentication, or the destroy approval workflow — those are independent of
AWS permissions entirely.

This does not mean zero configuration is ever needed again: the workload
still has to be **registered** in `config/finops-stacks.yml` (Step 2 above)
for the gate to know it exists, price it, and be allowed to deploy it. Full
AWS access removes the *IAM* step, not the *registration* step.

## Validated proof point

`ecommerce-platform` (69 resources across networking, ALB, ASGs, RDS,
ElastiCache, S3, CloudFront, Route 53, SQS, Secrets Manager, CloudWatch and
workload IAM) deployed successfully through this exact pipeline using the
shared full-access deploy role, with **no additional stack-specific IAM
permissions required** after the full-access model went live. It was later
torn down through the governed destroy workflow, reporting:

```
Apply complete! Resources: 0 added, 0 changed, 69 destroyed.
```

The two failures that occurred under the previous bounded-catalog design for
this same workload — `iam:CreateServiceLinkedRole` missing for ElastiCache,
and `s3:DeleteBucketPolicy` missing on destroy — did not recur. This
validates the reusable pipeline and the generic IAM model against one
substantially different real workload. It is **not** a claim that every AWS
service or resource type has been independently tested, that every
repository requires zero configuration, or that this is a least-privilege
production IAM design.

## Different GitHub repository

Everything above assumes the new Terraform root lives in *this* repo and
deploys to the AWS account this backend already controls. A workload in a
**separate** GitHub repository is not covered by simply copying the workflow
files — the deploy/plan roles' OIDC trust policy trusts a specific GitHub
subject claim (`repo:TanishqParab-Enc/finops-cost-engine-poc:environment:*`
today) and will reject `AssumeRoleWithWebIdentity` from any other repository.
Bringing a different repository under this same shared infrastructure
requires **both**:

- Copying `.github/workflows/finops-cost-gate.yml` (and
  `terraform-test-destroy.yml` if that repo also needs destroy) and
  `config/finops-stacks.yml` into it, **and**
- Intentionally widening the deploy/plan roles' OIDC trust policy to accept
  that repository's subject claim.

Or, more isolated: provision an entirely separate backend (its own
`deploy-role`/`plan-role`/OIDC trust) for that repository, following the same
bootstrap this repository used originally.

## Different AWS account

The shared backend — state bucket, OIDC provider, plan role, deploy role,
and the `DeployAnyWorkloadResource` full-access design — must be provisioned
for that account first (`backend/bootstrap` → `backend/environments/<env>`).
Only after that exists does registering a workload there reduce to Steps 1–2
above.
