# Support ticket routing

revision: r1

## Fields
- `category` (enum: billing, technical, account)
- `priority` (enum: low, normal, high, urgent)
- `wait_time` (number, minutes)

## Rules
- [R1] If `category` is missing, route to `manual_review`.
- [R2] Otherwise, if `priority` is `urgent`, route to `priority_queue`.
- [R3] Otherwise, if `wait_time` is at least 30 minutes, route to `escalation`.
- [R9] Otherwise, route to `normal_queue`.
