# Workflow

## Overview

Use this workflow for one payer-led group expense at a time.

The agent owns coordination.
The payer owns confirmation.
The scripts own deterministic transformations.

Prefer the shortest valid entry path:

- If the payer already knows the bill amount and token, start with manual bill creation.
- Only use transaction discovery when the payer needs help finding the source payment.

For the common dinner flow, do not force transaction discovery first.

## Happy Path: Manual Bill First

1. Resolve payer context.
2. Ask for bill amount and token.
3. Run `scripts/create_manual_bill_context.py`.
4. Ask for participant names and any optional wallet metadata.
5. Collect split instructions.
6. Run `scripts/parse_split_rules.py`.
7. Run `scripts/build_split_plan.py`.
8. Show the split draft to the payer.
9. Ask the payer to confirm the split draft.
10. Optionally enrich participants with wallet metadata via `scripts/resolve_participant_wallets.py`.
11. Run `scripts/generate_solana_pay_requests.py`.
12. Validate that the generated requests are canonical before publishing them.
13. **(Optional)** Run `scripts/render_payment_requests.py` with `--output-dir` when the host needs visible QR output as files.
14. Publish QR media first, then safe user-facing request text.
14. Run `scripts/watch_bill_status.py` whenever new payments arrive.
15. Close the bill when all requests are complete.

## Happy Path: Transaction Discovery

1. Resolve payer context.
2. Prepare a normalized wallet activity file.
3. Run `scripts/fetch_recent_transfers.py`.
4. Run `scripts/rank_expense_candidates.py`.
5. Ask the payer to confirm the source transaction.
6. Create the bill draft in the host application.
7. Collect split instructions.
8. Run `scripts/parse_split_rules.py`.
9. Run `scripts/build_split_plan.py`.
10. Show the split draft to the payer.
11. Ask the payer to confirm the split draft.
12. Optionally enrich participants with wallet metadata via `scripts/resolve_participant_wallets.py`.
13. Run `scripts/generate_solana_pay_requests.py`.
14. Validate that the generated requests are canonical before publishing them.
15. **(Optional)** Run `scripts/render_payment_requests.py` with `--output-dir` when the host needs visible QR output as files.
16. Publish QR media first, then safe user-facing request text.
16. Run `scripts/watch_bill_status.py` whenever new payments arrive.
17. Close the bill when all requests are complete.

## Recovery Path: No Transfer Candidates

If `fetch_recent_transfers.py` returns no eligible transfers:

1. Increase the lookback window.
2. Ask the payer for an amount hint.
3. Ask whether a different token was used.
4. Retry with updated filters.
5. If discovery still fails, ask for the bill amount and token directly.
6. Run `scripts/create_manual_bill_context.py`.
7. Continue with split parsing and split drafting.

Do not invent a source transaction.

## Recovery Path: Ambiguous Expense Candidate

If multiple ranked candidates remain plausible:

1. Present the top candidates.
2. Show amount, timestamp, counterparty label, and reason summary.
3. Ask the payer to choose.
4. If the payer cannot identify the transaction, fall back to manual bill amount entry.

Do not continue until the payer explicitly confirms one candidate or provides a manual bill amount.

## Recovery Path: Incomplete Split Instructions

If `parse_split_rules.py` cannot infer both the participant scope and the adjustment rules:

1. Ask for participant count or participant names.
2. Ask for any exceptions or fixed extra amounts.
3. Re-run the parser with the clarified text.

## Recovery Path: Missing Wallets

If `resolve_participant_wallets.py` returns missing participant wallets:

1. Continue with payment request generation.
2. Generate payment requests based on participant identity and amount due.
3. Ask for optional wallet binding only if it improves later verification or UX.

Do not block group settlement on unknown participant wallets.

## Recovery Path: Payment Gap

If `watch_bill_status.py` reports pending or underpaid requests:

1. Keep the bill open.
2. Notify the payer.
3. Remind the affected participants.
4. Re-check with the next payment batch.

## Artifact Flow

The host application should store and pass these artifacts between steps:

- filtered transfer candidates
- ranked expense candidates
- manual bill context when discovery fails
- parsed split rules
- split draft
- optional wallet enrichment output
- payment request bundle
- bill status snapshot

If QR sendable media exists, do not print local filesystem paths or raw `solana:` URIs into chat text. Deliver the QR as media and keep canonical machine fields internal.

Use stable file paths or artifact IDs. Avoid re-deriving artifacts that were already confirmed.
