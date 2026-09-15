# Orders accepted by the storefront are handed to the worker tier here, so the
# checkout path never blocks on fulfilment work.
resource "aws_sqs_queue" "orders" {
  name = "${var.name_prefix}-orders"

  message_retention_seconds  = var.retention_seconds
  visibility_timeout_seconds = var.visibility_timeout_seconds
  # Long polling: fewer empty receives, which is what SQS actually bills for.
  receive_wait_time_seconds = 20
  sqs_managed_sse_enabled   = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.orders_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = merge(var.tags, { Name = "${var.name_prefix}-orders" })
}

# Poison messages land here instead of being retried forever.
resource "aws_sqs_queue" "orders_dlq" {
  name = "${var.name_prefix}-orders-dlq"

  # Held longer than the main queue so a failed order can still be inspected.
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-orders-dlq" })
}

data "aws_iam_policy_document" "orders" {
  statement {
    sid    = "DenyUnencryptedTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions   = ["sqs:*"]
    resources = [aws_sqs_queue.orders.arn]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_sqs_queue_policy" "orders" {
  queue_url = aws_sqs_queue.orders.id
  policy    = data.aws_iam_policy_document.orders.json
}
