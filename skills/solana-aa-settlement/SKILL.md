---
name: solana-aa-settlement
description: Use when one payer already paid a shared expense and needs canonical Solana USDC reimbursement requests for multiple people after confirming or drafting the split; triggers include split bill after payment, reimburse friends, dinner AA, lunch AA, AA制, 分摊, 平摊, 谁该还钱.
---

# Solana AA Settlement

## Overview

Use this skill for one payer-led bill at a time.

Core principle: confirm the bill and confirm the split before generating any payment links.

Never handcraft a Solana Pay link in chat. Use the canonical script outputs, keep `reference` for reconciliation, and hide raw `reference` / `pay_url` from default end-user text unless an operator explicitly requests a debug view.

This skill is designed for the exact flow where one person already paid, then wants the agent to collect:

- total bill amount
- settlement token, usually `USDC`
- participant names
- optional participant Solana wallet addresses
- flexible split rules

After confirmation, the skill produces:

- a payer-confirmable split plan
- one Solana Pay request per reimbursing participant
- shareable payment links
- QR-ready output for chat or rendering runtimes
- payment-status tracking keyed by unique `reference`

## When to Use

Use this skill when:

- one person already covered a group expense
- the user wants an AA reimbursement bill instead of a generic invoice
- the payer can provide either the source transaction or the bill amount directly
- the split may be equal, weighted, custom, or exception-based
- some participants may not know their wallet address yet
- the host runtime needs per-person Solana payment links and QR output

Do not use this skill for:

- one-to-one invoices without group splitting
- non-Solana payment rails
- flows where the payer refuses to confirm the bill or the split

## Entry Modes

Choose the shortest valid path.

### 1. Manual bill mode — default for dinner AA collection

Use this first when the payer already knows the bill amount.

Example: Alice paid `100 USDC` for dinner and wants Bob, Carol, and Dave to reimburse their shares.

Collect:

- payer identity
- payer recipient wallet
- bill amount
- token symbol or mint, default `USDC`
- participant names
- optional participant wallets
- split instructions such as equal split, exclude payer, or custom weights

Then:

1. Run `scripts/create_manual_bill_context.py`.
2. Run `scripts/parse_split_rules.py`.
3. Run `scripts/build_split_plan.py`.
4. Show the split draft and wait for confirmation.
5. Run `scripts/resolve_participant_wallets.py` if wallet metadata is available.
6. Run `scripts/generate_solana_pay_requests.py`.
7. **(Optional)** Run `scripts/render_payment_requests.py` with `--output-dir` when the host needs visible QR output as files.
8. Run `scripts/watch_bill_status.py` as payments arrive.

### 2. Transaction-discovery mode — only when the payer needs help locating the expense

Use this when the payer wants the agent to find the likely source transaction on-chain.

Then:

1. Run `scripts/fetch_solana_wallet_activity.py` when you need fresh normalized activity from Solana mainnet RPC.
2. Prefer `--transport curl` in environments where `curl` is known to work more reliably than Python's network stack. Use `--transport auto` when you want automatic fallback from `urllib` to `curl`.
3. Run `scripts/fetch_recent_transfers.py`.
4. Run `scripts/rank_expense_candidates.py`.
5. Ask the payer to confirm the source transaction.
6. If discovery fails or the payer is unsure, switch back to manual bill mode instead of blocking the workflow.

## Required Inputs

| Input | Required | Notes |
|---|---|---|
| Payer recipient wallet | Yes | Needed before payment-request generation |
| Bill amount | Yes, unless confirmed from source transaction | Use manual mode when amount is already known |
| Token | Usually yes | Default to `USDC` |
| Participant names or IDs | Yes | Needed for split drafting and request generation |
| Participant wallets | No | Helpful metadata only |
| Split rules | Yes | Equal, weighted, fixed extras, exclusions, or custom adjustments |

## Quick Reference

| Need | Script | Result |
|---|---|---|
| Create bill from known amount | `scripts/create_manual_bill_context.py` | deterministic bill context |
| Parse freeform split rules | `scripts/parse_split_rules.py` | structured split instructions |
| Build payer-facing draft | `scripts/build_split_plan.py` | confirmed split plan |
| Add optional wallet metadata | `scripts/resolve_participant_wallets.py` | enriched participant records |
| Generate per-person payment requests | `scripts/generate_solana_pay_requests.py` | Solana Pay links + references |
| Produce visible QR output (optional) | `scripts/render_payment_requests.py` | HTML, Markdown, sendable image metadata (use `--output-dir` to write files) |
| Track who still owes | `scripts/watch_bill_status.py` | bill status snapshot |

## Confirmation Rules

Always enforce these rules:

1. Never auto-select the source transaction.
2. Always show the split draft before creating payment requests.
3. Generate one payment request per reimbursing participant.
4. Track each payment request with a unique Solana `reference`.
5. Close the bill only after all tracked requests are complete.

If the payer changes the participant list or split instructions after seeing the draft, rebuild the split plan and discard any unconfirmed downstream artifacts.

## Skill Output Contract

Expect every bundled script to return a JSON object with these top-level fields:

- `status`
- `summary`
- `next_actions`
- `artifacts`
- `data`

Treat `status` as one of:

- `success`
- `warning`
- `error`

Use `artifacts` for file paths or artifact identifiers that the next step should consume.

For chat runtimes that can send media, prefer explicit QR image metadata over plain text links when `scripts/render_payment_requests.py` is used:

- `data.outbound_media` — top-level list of host-sendable media items
- `data.request_views[].qr_sendable_media` — per-request image metadata

Each QR media item includes:

- `type: image`
- `transport_hint: sendPhoto`
- `source` — local file path or remote image URL
- `source_type` — `path` or `url`
- `caption`

Host runtimes such as OpenClaw should prefer these fields when sending visible QR codes into Telegram or other chat channels. Do not assume that `qr_image_src`, Markdown, or HTML artifacts alone will be rendered as an inline image by the chat platform.

If `data.outbound_media` exists, treat it as the mandatory-first delivery path. Do not substitute `chat_share_text`, raw `pay_url`, or local filesystem path text when the runtime can send the structured media directly.

Read [references/contracts.md](references/contracts.md) for normalized object shapes and script-level input and output expectations.

## Scripts

Run these scripts for deterministic steps:

- `scripts/fetch_solana_wallet_activity.py`
  Purpose: fetch and normalize recent Solana mainnet wallet activity from a standard RPC endpoint, with `curl` fallback support and optional provider headers.
- `scripts/fetch_recent_transfers.py`
  Purpose: filter normalized wallet activity into recent outgoing transfer candidates.
- `scripts/rank_expense_candidates.py`
  Purpose: score candidate transfers and return ranked expense options.
- `scripts/create_manual_bill_context.py`
  Purpose: create a deterministic bill context from user-provided amount and token when transaction discovery fails or is unnecessary.
- `scripts/parse_split_rules.py`
  Purpose: convert freeform split text into structured split rules.
- `scripts/build_split_plan.py`
  Purpose: compute the payer-confirmable split draft.
- `scripts/resolve_participant_wallets.py`
  Purpose: optionally attach known wallet addresses to participants; missing participant wallets should not block request generation.
- `scripts/generate_solana_pay_requests.py`
  Purpose: create participant-specific Solana Pay requests after split confirmation, even when participant wallets are unknown.
- `scripts/render_payment_requests.py`
  Purpose: render payment requests into HTML and Markdown, expose visible QR output by default for chat-based runtimes, and emit host-sendable image metadata for QR delivery. When `--output-dir` is provided, files are written to disk; otherwise only JSON output is returned without file generation.
- `scripts/watch_bill_status.py`
  Purpose: evaluate payment completion by matching observed payments against generated requests.

Use `scripts/common.py` only as an implementation helper. Do not invoke it directly.

## References

Read only the reference file needed for the step you are handling:

- Read [references/workflow.md](references/workflow.md) for the full orchestration path and recovery branches.
- Read [references/contracts.md](references/contracts.md) for normalized object schemas and artifact contracts.
- Read [references/transaction-discovery.md](references/transaction-discovery.md) when fetching wallet activity, preparing wallet activity inputs, or ranking expense candidates.
- Read [references/solana-pay.md](references/solana-pay.md) when generating payment requests or validating `reference` usage.
- Read [references/state-machine.md](references/state-machine.md) when deciding whether a transition is legal.

## Common Mistakes

- Generating payment links before the payer confirms the split draft.
- Treating participant wallet addresses as mandatory instead of optional metadata.
- Staying in transaction-discovery mode when the payer already knows the bill amount.
- Reusing the same `reference` for multiple participants.
- Putting sensitive information into `memo` fields that will be recorded on-chain.
- Using anything other than the payer's native Solana account as the Solana Pay `recipient`.

## Error Recovery Rules

When a script returns `warning` or `error`, follow the `next_actions` field first.

Apply these recovery patterns:

- If no transfer candidates are found, widen the time window or ask for amount and token hints.
- If transaction discovery still fails, ask the payer for bill amount and token, run `scripts/create_manual_bill_context.py`, and continue with split drafting.
- If multiple expense candidates score similarly, ask the payer to choose explicitly.
- If split parsing is incomplete, ask the payer to restate participant count and custom adjustments.
- If participant wallets are missing, continue generating identity-based payment requests and ask for optional wallet binding only when it improves downstream tracking.
- If a payment is missing or underpaid, keep the bill open and issue reminders instead of regenerating requests.
- If public RPC calls fail or rate-limit, retry with backoff, switch to `--transport curl`, or move to a dedicated mainnet RPC provider.

Stop the flow if the payer cannot confirm either the source transaction or the split draft and also refuses to provide a manual bill amount.

## Validation Checklist

Before relying on this skill in a live workflow:

1. Validate the skill folder with `quick_validate.py`.
2. Validate every script with representative JSON inputs.
3. Verify that split confirmation happens before payment request generation.
4. Verify that every generated request has a unique `reference`.
5. Verify that bill closure only happens after all requests are marked paid.
6. Verify that mainnet RPC reads return structured errors instead of uncaught exceptions.
7. Verify that the manual bill path still produces a valid split draft when transaction discovery is skipped entirely.
8. Verify that `--transport curl` succeeds in environments where direct Python HTTP requests are unreliable.
9. Verify that missing participant wallet addresses do not block payment request generation.
