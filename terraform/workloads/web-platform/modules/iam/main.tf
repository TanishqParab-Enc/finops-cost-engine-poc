data "aws_iam_policy_document" "assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${var.name_prefix}-instance-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json

  tags = var.tags
}

# Scoped to this workload's own bucket and log group only - no wildcards on
# resource ARNs.
data "aws_iam_policy_document" "instance" {
  statement {
    sid    = "ReadWriteAssetBucket"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${var.assets_bucket_arn}/*"]
  }

  statement {
    sid       = "ListAssetBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [var.assets_bucket_arn]
  }

  statement {
    sid    = "WriteApplicationLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${var.log_group_arn}:*"]
  }
}

resource "aws_iam_role_policy" "instance" {
  name   = "${var.name_prefix}-instance-policy"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "${var.name_prefix}-instance-profile"
  role = aws_iam_role.instance.name

  tags = var.tags
}
