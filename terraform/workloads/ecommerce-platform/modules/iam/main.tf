data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  # RDS generates and rotates the master credential itself, so its secret ARN
  # only exists after apply. Referencing it directly would leave an unknown
  # value in this policy and break a greenfield plan, so the grant is scoped to
  # the `rds!` reserved prefix in this account and region instead - still far
  # narrower than secretsmanager:* on a wildcard resource.
  rds_managed_secrets = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:rds!*"

  # Built from the log group NAMES rather than the monitoring module's outputs.
  # The monitoring module's alarms reference the compute tiers, the compute
  # tiers reference these instance profiles, and taking the ARNs from
  # monitoring would close that loop into a dependency cycle. The names are
  # deterministic, so deriving the ARNs here is equivalent and acyclic.
  logs_prefix       = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group"
  app_log_group_arn = "${local.logs_prefix}:${var.app_log_group_name}"
  wrk_log_group_arn = "${local.logs_prefix}:${var.worker_log_group_name}"
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# -- storefront tier ---------------------------------------------------------
# Serves the catalogue, reads/writes assets, publishes orders, reads config.
# It may SEND to the queue but never RECEIVE from it - only workers consume.
data "aws_iam_policy_document" "app" {
  statement {
    sid    = "ReadWriteProductAssets"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]

    resources = ["${var.asset_bucket_arn}/*"]
  }

  statement {
    sid       = "ListProductAssets"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [var.asset_bucket_arn]
  }

  statement {
    sid    = "PublishOrderEvents"
    effect = "Allow"

    actions = [
      "sqs:SendMessage",
      "sqs:GetQueueUrl",
      "sqs:GetQueueAttributes",
    ]

    resources = [var.order_queue_arn]
  }

  statement {
    sid       = "ReadApplicationConfig"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.app_secret_arn]
  }

  statement {
    sid       = "ReadDatabaseCredentials"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.rds_managed_secrets]
  }

  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = ["${local.app_log_group_arn}:*"]
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.name_prefix}-app-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json

  tags = merge(var.tags, { Name = "${var.name_prefix}-app-role", Tier = "application" })
}

resource "aws_iam_role_policy" "app" {
  name   = "${var.name_prefix}-app-policy"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app.json
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.name_prefix}-app-profile"
  role = aws_iam_role.app.name

  tags = merge(var.tags, { Name = "${var.name_prefix}-app-profile" })
}

# -- worker tier -------------------------------------------------------------
# Consumes orders and writes fulfilment artefacts. It may RECEIVE and DELETE
# from the queue but never SEND - only the storefront produces orders.
data "aws_iam_policy_document" "worker" {
  statement {
    sid    = "ConsumeOrderEvents"
    effect = "Allow"

    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueUrl",
      "sqs:GetQueueAttributes",
    ]

    resources = [var.order_queue_arn]
  }

  statement {
    sid       = "InspectDeadLetters"
    effect    = "Allow"
    actions   = ["sqs:ReceiveMessage", "sqs:GetQueueAttributes"]
    resources = [var.order_dlq_arn]
  }

  statement {
    sid    = "WriteFulfilmentArtefacts"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]

    resources = ["${var.asset_bucket_arn}/*"]
  }

  statement {
    sid       = "ReadDatabaseCredentials"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.rds_managed_secrets]
  }

  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = ["${local.wrk_log_group_arn}:*"]
  }
}

resource "aws_iam_role" "worker" {
  name               = "${var.name_prefix}-worker-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json

  tags = merge(var.tags, { Name = "${var.name_prefix}-worker-role", Tier = "worker" })
}

resource "aws_iam_role_policy" "worker" {
  name   = "${var.name_prefix}-worker-policy"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

resource "aws_iam_instance_profile" "worker" {
  name = "${var.name_prefix}-worker-profile"
  role = aws_iam_role.worker.name

  tags = merge(var.tags, { Name = "${var.name_prefix}-worker-profile" })
}
