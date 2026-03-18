# Transaction Discovery

## Overview

Use transaction discovery to narrow a payer's recent wallet activity into likely expense candidates.

This skill can fetch normalized activity directly from Solana mainnet RPC with `scripts/fetch_solana_wallet_activity.py`, or consume a normalized wallet activity export prepared by another component.

## Input Expectations

Preferred path:

1. fetch wallet activity with `scripts/fetch_solana_wallet_activity.py`
2. prefer `--transport curl` in environments where `curl` is known to be more reliable than Python HTTP
3. filter the normalized records with `scripts/fetch_recent_transfers.py`
4. rank those candidates with `scripts/rank_expense_candidates.py`

Recommended upstream sources when not using the bundled fetcher:

- Solana RPC plus transfer normalization
- indexed transaction providers such as Helius
- host application transaction cache

Do not feed raw unnormalized transaction payloads directly into the ranking script.

## Fetch Strategy

`fetch_solana_wallet_activity.py` uses standard Solana JSON-RPC:

- `getSignaturesForAddress`
- `getTransaction`

It supports three transport modes:

- `auto`: try Python `urllib` first, then fall back to `curl`
- `urllib`: force Python HTTP transport
- `curl`: force `curl` transport

It also supports provider-specific headers with repeatable `--http-header KEY=VALUE` arguments.

Use it when:

- the runtime needs fresh wallet activity
- the host application does not already cache normalized transfers
- you want a portable, runtime-independent fetch step

## Mainnet Public RPC Endpoint

As of `2026-03-16`, Solana's official cluster docs list this public mainnet endpoint:

- `https://api.mainnet.solana.com`

Use it carefully:

- it is free and public
- it is rate-limited
- limits may change without notice
- it is not suitable for production payment infrastructure

The bundled fetcher keeps `--rpc-url` configurable, but mainnet is the only supported public-cluster assumption in this repository.

## Recommended Invocation

In environments where Python HTTP is unreliable but shell `curl` works, prefer:

```bash
python scripts/fetch_solana_wallet_activity.py \
  --transport curl \
  --wallet-address "<wallet>" \
  --rpc-url "https://api.mainnet.solana.com" \
  --include-native \
  --max-normalized-transfers 5 \
  --limit 10
```

If you are unsure, start with:

```bash
python scripts/fetch_solana_wallet_activity.py \
  --transport auto \
  --wallet-address "<wallet>" \
  --rpc-url "https://api.mainnet.solana.com"
```

## Filtering Strategy

Apply these filters before ranking:

- recent time window
- target token such as `USDC`
- outgoing direction
- minimum amount greater than dust

The `fetch_recent_transfers.py` script implements this filtering step.

## Ranking Heuristics

The ranking script works best when records include:

- `counterparty_label`
- `memo`
- `kind`

Score these signals:

- outgoing transaction
- recency
- exact or overlapping intent keywords between the user message and candidate metadata
- amount plausibility for a shared expense

Meal-related language in the user request should bias toward records with matching words such as:

- dinner
- lunch
- restaurant
- cafe
- bar
- food

## Candidate Selection Rules

Never auto-select the source transaction.

Always:

1. show the top candidates
2. include reason summaries
3. ask the payer to confirm

## Missing Data Strategy

If labels or memos are absent:

- rely more heavily on recency and amount
- reduce confidence
- ask for explicit payer confirmation

If no matching token is found:

- retry with a wider token filter
- ask the payer which token was used
