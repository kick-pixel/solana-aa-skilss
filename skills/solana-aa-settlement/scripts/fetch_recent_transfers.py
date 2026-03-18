import argparse

from common import decimalize, emit, isoformat_utc, parse_timestamp, read_json, response, utc_now, window_start


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Filter normalized wallet activity into recent transfer candidates.")
    parser.add_argument("--input-file", required=True, help="JSON array of normalized transfer records or an upstream artifact containing data.transfers.")
    parser.add_argument("--wallet-address", required=True)
    parser.add_argument("--token", default="USDC")
    parser.add_argument("--lookback-minutes", type=int, default=180)
    parser.add_argument("--direction", choices=["incoming", "outgoing", "any"], default="outgoing")
    parser.add_argument("--min-amount", default="1")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--now", default=None, help="Override current time with an ISO timestamp.")
    parser.add_argument("--output-file", default=None)
    return parser


def unwrap_records(raw_payload):
    if isinstance(raw_payload, list):
        return raw_payload
    if isinstance(raw_payload, dict):
        return raw_payload.get("data", {}).get("transfers", [])
    return []


def main() -> None:
    args = build_parser().parse_args()
    records = unwrap_records(read_json(args.input_file))
    now_value = utc_now(args.now)
    cutoff = window_start(now_value, args.lookback_minutes)
    min_amount = decimalize(args.min_amount)

    filtered = []
    for record in records:
        try:
            timestamp = parse_timestamp(record["timestamp"])
            amount = decimalize(record["amount"])
        except Exception:
            continue
        if timestamp < cutoff:
            continue
        if amount < min_amount:
            continue
        direction = str(record.get("direction", "any")).lower()
        if args.direction != "any" and direction != args.direction:
            continue
        token_symbol = str(record.get("token_symbol", "")).upper()
        token_mint = str(record.get("token_mint", "")).upper()
        if args.token and args.token.upper() not in {token_symbol, token_mint}:
            continue
        owner = record.get("owner")
        if owner and owner != args.wallet_address:
            continue
        filtered.append(
            {
                "signature": record.get("signature"),
                "timestamp": isoformat_utc(timestamp),
                "amount": str(amount),
                "direction": direction,
                "token_symbol": token_symbol,
                "token_mint": record.get("token_mint", ""),
                "counterparty": record.get("counterparty") or record.get("destination"),
                "counterparty_label": record.get("counterparty_label"),
                "memo": record.get("memo"),
                "kind": record.get("kind"),
            }
        )

    filtered.sort(key=lambda item: item["timestamp"], reverse=True)
    filtered = filtered[: args.limit]

    if not filtered:
        payload = response(
            "error",
            f"No outgoing {args.token} transfers found in the last {args.lookback_minutes} minutes",
            ["expand_time_window", "ask_user_for_transaction_amount"],
            [],
            {
                "wallet_address": args.wallet_address,
                "count": 0,
                "lookback_minutes": args.lookback_minutes,
                "window_start": isoformat_utc(cutoff),
                "window_end": isoformat_utc(now_value),
            },
        )
        emit(payload, args.output_file)
        return

    payload = response(
        "success",
        f"Found {len(filtered)} recent transfer candidates",
        ["rank_expense_candidates"],
        [args.output_file] if args.output_file else [],
        {
            "wallet_address": args.wallet_address,
            "count": len(filtered),
            "lookback_minutes": args.lookback_minutes,
            "window_start": isoformat_utc(cutoff),
            "window_end": isoformat_utc(now_value),
            "transfers": filtered,
        },
    )
    emit(payload, args.output_file)


if __name__ == "__main__":
    main()
