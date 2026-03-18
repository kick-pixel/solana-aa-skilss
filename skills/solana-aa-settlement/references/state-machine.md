# State Machine

## Bill States

- `draft`
- `awaiting_transaction_confirmation`
- `awaiting_split_rules`
- `awaiting_split_confirmation`
- `payment_requests_preparing`
- `payment_requests_generated`
- `partially_paid`
- `paid`
- `closed`
- `cancelled`

## Legal Transitions

- `draft` -> `awaiting_transaction_confirmation`
- `awaiting_transaction_confirmation` -> `awaiting_split_rules`
- `awaiting_split_rules` -> `awaiting_split_confirmation`
- `awaiting_split_confirmation` -> `payment_requests_preparing`
- `payment_requests_preparing` -> `payment_requests_generated`
- `payment_requests_generated` -> `partially_paid`
- `payment_requests_generated` -> `paid`
- `partially_paid` -> `paid`
- `paid` -> `closed`

## Guard Conditions

Apply these guards:

- do not enter `awaiting_split_rules` without a payer-confirmed transaction or manual bill context
- do not enter `payment_requests_preparing` without a split draft
- do not enter `payment_requests_generated` without split confirmation
- do not enter `closed` without all payment requests marked paid

## Reminder Rule

Allow reminders only in:

- `payment_requests_generated`
- `partially_paid`

Do not remind participants before a bill has live payment requests.

## Reset Rule

If the payer changes the participant set or split logic after confirmation:

1. move the bill back to `awaiting_split_confirmation`
2. discard untrusted downstream request artifacts
3. rebuild the split draft
