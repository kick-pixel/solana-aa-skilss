import argparse

from common import decimalize, emit, money_string, normalize_identifier, response


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a manual bill context when transaction discovery is unavailable or inconclusive.")
    parser.add_argument("--bill-amount", required=True)
    parser.add_argument("--token-symbol", default="USDC")
    parser.add_argument("--token-mint", default="")
    parser.add_argument("--payer-id", required=True)
    parser.add_argument("--source-mode", default="manual", choices=["manual", "fallback"])
    parser.add_argument("--note", default="")
    parser.add_argument("--output-file", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    bill_amount = decimalize(args.bill_amount)
    if bill_amount <= 0:
        payload = response(
            "error",
            "Manual bill amount must be greater than zero",
            ["set_positive_bill_amount"],
            [],
            {"bill_amount": str(bill_amount)},
        )
        emit(payload, args.output_file)
        return

    payload = response(
        "success",
        "Created manual bill context",
        ["parse_split_rules", "build_split_plan"],
        [args.output_file] if args.output_file else [],
        {
            "bill_amount": money_string(bill_amount),
            "token_symbol": args.token_symbol.upper(),
            "token_mint": args.token_mint,
            "payer_id": normalize_identifier(args.payer_id),
            "source_mode": args.source_mode,
            "note": args.note,
        },
    )
    emit(payload, args.output_file)


if __name__ == "__main__":
    main()
