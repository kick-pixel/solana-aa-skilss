# Contracts

## Script Response Contract

Every script returns a JSON object with:

```json
{
  "status": "success",
  "summary": "One-line result",
  "next_actions": ["step_a"],
  "artifacts": ["artifact.json"],
  "data": {}
}
```

Rules:

- `status` is `success`, `warning`, or `error`
- `summary` is one sentence
- `next_actions` is always an array
- `artifacts` is always an array
- `data` holds the main payload

## Wallet Activity Fetch Output

`fetch_solana_wallet_activity.py` returns:

```json
{
  "wallet_address": "payer-wallet-address",
  "rpc_url": "https://api.mainnet.solana.com",
  "transport_used": "curl",
  "transaction_count": 12,
  "max_normalized_transfers": 50,
  "transfers": []
}
```

Supported transport modes:

- `urllib`
- `curl`
- `auto`

`auto` tries Python `urllib` first and falls back to `curl` when possible.

`max_normalized_transfers` lets the fetcher stop early once it has gathered enough unique transfer records. Use it to reduce pressure on public mainnet RPC endpoints.

The fetcher also accepts repeatable provider headers:

```text
--http-header KEY=VALUE
```

## Manual Bill Context Output

`create_manual_bill_context.py` returns:

```json
{
  "bill_amount": "268.00",
  "token_symbol": "USDC",
  "token_mint": "",
  "payer_id": "alice",
  "source_mode": "manual",
  "note": "Dinner bill entered manually after transaction lookup failed"
}
```

Use this artifact when transaction discovery fails or remains ambiguous after user review.

## Normalized Transfer Record

Use this shape for wallet activity inputs:

```json
{
  "signature": "5N...",
  "timestamp": "2026-03-16T11:42:00Z",
  "owner": "payer-wallet-address",
  "source": "payer-wallet-address",
  "destination": "merchant-or-counterparty-wallet",
  "direction": "outgoing",
  "amount": "268.00",
  "token_symbol": "USDC",
  "token_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
  "counterparty": "merchant-or-counterparty-wallet",
  "counterparty_label": "Dinner Merchant",
  "memo": "team dinner",
  "kind": "payment"
}
```

Required fields:

- `signature`
- `timestamp`
- `amount`

Recommended fields:

- `direction`
- `token_symbol`
- `counterparty_label`
- `memo`
- `kind`

## Recent Transfer Filter Input

`fetch_recent_transfers.py` accepts either:

1. a raw JSON array of normalized transfer records
2. an upstream artifact where normalized records live under `data.transfers`

This lets the script consume the direct output of `fetch_solana_wallet_activity.py` without a separate adapter step.

## Ranked Candidate

`rank_expense_candidates.py` returns transaction-level candidates, not per-instruction rows.
Multiple transfer instructions with the same `signature` are collapsed into one candidate.

```json
{
  "signature": "5N...",
  "score": 0.92,
  "timestamp": "2026-03-16T11:42:00Z",
  "amount": "268.00",
  "token_symbol": "USDC",
  "counterparty_label": "Dinner Merchant",
  "instruction_count": 2,
  "reason_summary": [
    "recent outgoing payment",
    "matched intent keywords: dinner"
  ]
}
```

## Parsed Split Rules

`parse_split_rules.py` returns:

```json
{
  "participant_count": 5,
  "excluded_participants": [],
  "adjustments": [
    {
      "participant_id": "alice",
      "delta_amount": "20.00"
    },
    {
      "participant_id": "bob",
      "delta_amount": "20.00"
    }
  ],
  "raw_text": "5 people, Bob and I pay 20 more"
}
```

The parser accepts natural variants such as `pay` and `pays`, and supports comma-separated subject lists.

`delta_amount` is relative to the even base share:

- positive means pay more
- negative means pay less

## Participant Input

Use either of these shapes in participant files:

```json
["alice", "bob", "carol"]
```

or

```json
[
  {"id": "alice", "display_name": "Alice"},
  {"id": "bob", "display_name": "Bob"}
]
```

## Split Plan

`build_split_plan.py` returns:

```json
{
  "bill_amount": "268.00",
  "payer_id": "alice",
  "participants": [
    {
      "participant_id": "alice",
      "display_name": "Alice",
      "is_payer": true,
      "share_amount": "65.60",
      "reimbursement_amount": "0.00"
    },
    {
      "participant_id": "bob",
      "display_name": "Bob",
      "is_payer": false,
      "share_amount": "65.60",
      "reimbursement_amount": "65.60"
    }
  ]
}
```

The split builder fails fast if:

- bill amount is not positive
- payer is missing from the participant list
- split adjustments reference participant IDs that are not in the participant list
- any participant would end up with a negative share

## Wallet Resolution Output

`resolve_participant_wallets.py` optionally enriches split participants with wallet metadata:

```json
{
  "participants": [
    {
      "participant_id": "bob",
      "display_name": "Bob",
      "share_amount": "65.60",
      "reimbursement_amount": "65.60",
      "wallet_address": "wallet-address",
      "wallet_status": "resolved"
    }
  ],
  "missing_wallet_participants": ["emma"]
}
```

The wallet-book input is optional. If omitted, request generation should still continue with identity-based requests.

## Payment Request Output

`generate_solana_pay_requests.py` returns identity-based requests even when participant wallets are unknown:

```json
{
  "recipient_wallet": "payer-wallet-address",
  "token_symbol": "USDC",
  "token_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
  "requests": [
    {
      "request_id": "bill-001:bob",
      "participant_id": "bob",
      "participant_wallet": null,
      "wallet_status": "missing",
      "amount": "65.60",
      "reference": "base58-reference",
      "pay_url": "solana:...",
      "qr_payload": "solana:...",
      "memo": "bill:bill-001:bob"
    }
  ],
  "missing_wallet_participants": ["bob"]
}
```

Known participant wallets are optional metadata. The request generator must not fail only because participant wallets are missing.

Treat `reference`, `memo`, and `pay_url` as internal reconciliation fields. They are canonical machine data, not default end-user display text.

## Rendered Payment Request Output

`render_payment_requests.py` returns host-sendable QR image metadata in addition to HTML and Markdown artifacts. It also separates internal request views from default public request views:

```json
{
  "qr_mode": "remote_url",
  "rendered_files": {
    "html": "path/to/payment_requests.html",
    "markdown": "path/to/payment_requests.md"
  },
  "request_views": [
    {
      "request_id": "bill-001:bob",
      "reference": "base58-reference",
      "pay_url": "solana:...",
      "qr_image_src": "https://...",
      "qr_sendable_media": {
        "type": "image",
        "transport_hint": "sendPhoto",
        "source": "https://...",
        "source_type": "url",
        "caption": "Bob payment QR for 65.60 via Solana Pay"
      }
    }
  ],
  "public_request_views": [
    {
      "request_id": "bill-001:bob",
      "display_name": "Bob",
      "amount": "65.60",
      "qr_image_src": "https://...",
      "wallet_open_action": {
        "type": "wallet_open_action",
        "label": "Open in wallet from a compatible runtime"
      }
    }
  ],
  "outbound_media": [
    {
      "type": "image",
      "transport_hint": "sendPhoto",
      "source": "https://...",
      "source_type": "url",
      "request_id": "bill-001:bob"
    }
  ]
}
```

Host runtimes should prefer `outbound_media` or `request_views[].qr_sendable_media` when they need to send visible QR images to chat channels instead of only showing text or artifact paths.

Delivery priority:

1. `outbound_media`
2. `request_views[].qr_sendable_media`
3. `public_request_views[].wallet_open_action`
4. text fallback without raw `reference`, local file paths, or raw `solana:` URIs

Do not print local filesystem paths such as `/home/.../qr.png` to end users. Use them only as host-sendable media sources.

If `outbound_media` is non-empty and the host can send images, it must send that media first instead of falling back to `chat_share_text`.

## Observed Payment Record

Use this shape for the payment watcher input:

```json
{
  "reference": "base58-reference",
  "amount": "65.60",
  "payer_wallet": "participant-wallet",
  "signature": "4K...",
  "confirmed_at": "2026-03-16T12:10:00Z"
}
```

## Bill Status Snapshot

`watch_bill_status.py` returns:

```json
{
  "bill_status": "partially_paid",
  "total_due": "202.40",
  "total_paid": "136.80",
  "remaining_due": "65.60",
  "participant_statuses": [
    {
      "participant_id": "bob",
      "request_status": "paid",
      "paid_amount": "65.60"
    }
  ]
}
```
