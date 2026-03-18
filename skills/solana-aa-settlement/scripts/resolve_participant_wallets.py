import argparse

from common import emit, load_wallet_book, response, read_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optionally attach known wallet addresses to split plan participants.")
    parser.add_argument("--split-plan-file", required=True)
    parser.add_argument("--wallet-book-file", default=None)
    parser.add_argument("--output-file", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    split_plan = read_json(args.split_plan_file).get("data", {})
    wallet_book = load_wallet_book(args.wallet_book_file) if args.wallet_book_file else {}

    enriched = []
    missing_wallets = []
    reimbursing_count = 0
    for participant in split_plan.get("participants", []):
        participant_id = participant["participant_id"]
        reimbursement_amount = participant.get("reimbursement_amount", "0.00")
        wallet = wallet_book.get(participant_id)
        needs_payment_request = reimbursement_amount != "0.00"
        wallet_status = "resolved" if wallet else "missing"
        if needs_payment_request:
            reimbursing_count += 1
            if not wallet:
                missing_wallets.append(participant_id)
        enriched.append({**participant, "wallet_address": wallet, "wallet_status": wallet_status})

    status = "success" if not missing_wallets else "warning"
    summary = f"Resolved wallets for {reimbursing_count - len(missing_wallets)} of {reimbursing_count} reimbursing participants"
    next_actions = ["generate_payment_requests"]
    if missing_wallets:
        next_actions.append("request_optional_wallet_binding")
    payload = response(
        status,
        summary,
        next_actions,
        [args.output_file] if args.output_file else [],
        {
            "bill_amount": split_plan.get("bill_amount"),
            "payer_id": split_plan.get("payer_id"),
            "participants": enriched,
            "missing_wallet_participants": missing_wallets,
        },
    )
    emit(payload, args.output_file)


if __name__ == "__main__":
    main()
