# Solana Pay

## Purpose

Use Solana Pay for participant-specific reimbursement requests.

Generate one payment request per reimbursing participant instead of one shared wallet address.

## URI Pattern

Use this URI shape:

```text
solana:<recipient>?amount=<amount>&spl-token=<mint>&reference=<reference>&label=<label>&message=<message>&memo=<memo>
```

Treat `token=` as invalid. Canonical SPL-token payment requests use `spl-token=`.

## Required Fields

- `recipient`
- `amount`
- `reference`

Use `spl-token` for SPL-token settlement such as `USDC`.

`recipient` must be the payer's native Solana account, not an associated token account.

## USDC on Solana

For MVP, default to Solana USDC:

- symbol: `USDC`
- mint: `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`

## Reference Rules

Treat `reference` as the primary reconciliation key.

Rules:

- generate a unique reference for every request
- never reuse the same reference across participants
- keep the reference stable after request generation
- match observed payments by reference first
- use base58-compatible 32-byte values for Solana Pay compatibility

Human-readable values such as `AA-DINNER-001-BLOB` are invalid as canonical references.

## Label and Message Rules

Keep labels short and human-readable.

Suggested pattern:

- label: `AA Settlement`
- message: `Reimburse Alice for dinner`
- memo: `bill:<bill_id>:<participant_id>`

Do not put private information into `memo`. It is recorded on-chain.

## Identity-Based Requests

Participant wallet addresses are optional for request generation.

The request generator should always be able to create a participant-specific payment request from:

- payer recipient wallet
- participant identity
- participant amount due
- unique reference

If participant wallets are known, include them as metadata for stronger reconciliation and UX.
If participant wallets are unknown, still generate the payment request and track it by reference.

## QR Handling

For MVP, the request generator still produces the final Solana Pay URI.

The runtime should also expose a visible QR output by default, because many chat surfaces cannot directly open `solana:` links.

Preferred order:

- local QR image generation when a QR library is available
- otherwise a visible remote QR image URL
- plain link-only output only when the runtime explicitly disables remote QR

When the runtime cannot open `solana:` links directly, send the QR image first. Keep the raw payment link for debug or operator workflows instead of default user-facing text.

In chat-based runtimes, do not claim that a QR has been sent unless an actual image, image URL, or rendered page is available to the user.

In default end-user text, do not expose the raw `reference`, local QR file paths, or the full raw `solana:` URI.

## Validation Rules

Before publishing a request:

1. Verify that the payer recipient wallet is present.
2. Verify that the reimbursement amount is greater than zero.
3. Verify that the token mint matches the intended settlement token.
4. Verify that the reference is unique within the bill.
5. Treat participant wallets as optional metadata, not a hard precondition.
