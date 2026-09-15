output "queue_arn" {
  description = "Order queue ARN, used to scope the tier IAM policies."
  value       = aws_sqs_queue.orders.arn
}

output "queue_url" {
  description = "Order queue URL the storefront publishes to and workers poll."
  value       = aws_sqs_queue.orders.url
}

output "queue_name" {
  description = "Order queue name, used as the CloudWatch alarm dimension."
  value       = aws_sqs_queue.orders.name
}

output "dlq_arn" {
  description = "Dead-letter queue ARN."
  value       = aws_sqs_queue.orders_dlq.arn
}

output "dlq_name" {
  description = "Dead-letter queue name, used as the CloudWatch alarm dimension."
  value       = aws_sqs_queue.orders_dlq.name
}
