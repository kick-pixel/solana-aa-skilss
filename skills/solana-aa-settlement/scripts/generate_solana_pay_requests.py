import argparse
from urllib.parse import urlencode

from common import emit, random_reference, response, read_json


DEFAULT_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate participant-specific Solana Pay requests."
    )
    parser.add_argument("--wallet-resolution-file", required=True)
    parser.add_argument("--recipient-wallet", required=True)
    parser.add_argument("--bill-id", required=True)
    parser.add_argument("--token-symbol", default="USDC")
    parser.add_argument("--token-mint", default=DEFAULT_USDC_MINT)
    parser.add_argument("--label", default="AA Settlement")
    parser.add_argument("--message", default="Reimburse the payer")
    parser.add_argument("--output-file", default=None)
    return parser


def build_pay_url(
    recipient_wallet: str,
    amount: str,
    token_mint: str,
    reference: str,
    label: str,
    message: str,
    memo: str,
) -> str:
    params = urlencode(
        {
            "amount": amount,
            "spl-token": token_mint,
            "reference": reference,
            "label": label,
            "message": message,
            "memo": memo,
        }
    )
    return f"solana:{recipient_wallet}?{params}"


def main() -> None:
    args = build_parser().parse_args()
    resolution = read_json(args.wallet_resolution_file).get("data", {})

    if not args.recipient_wallet.strip():
        payload = response(
            "error",
            "Recipient wallet is required to generate payment requests",
            ["set_recipient_wallet"],
            [],
            {},
        )
        emit(payload, args.output_file)
        return

    requests = []
    seen_references = set()
    missing_wallet_participants = []
    for participant in resolution.get("participants", []):
        amount = participant.get("reimbursement_amount", "0.00")
        if amount == "0.00":
            continue
        if float(amount) <= 0:
            continue
        if not participant.get("wallet_address"):
            missing_wallet_participants.append(participant["participant_id"])
        reference = random_reference()
        while reference in seen_references:
            reference = random_reference()
        seen_references.add(reference)
        memo = f"bill:{args.bill_id}:{participant['participant_id']}"
        pay_url = build_pay_url(
            args.recipient_wallet,
            amount,
            args.token_mint,
            reference,
            args.label,
            args.message,
            memo,
        )
        requests.append(
            {
                "request_id": f"{args.bill_id}:{participant['participant_id']}",
                "participant_id": participant["participant_id"],
                "display_name": participant.get("display_name"),
                "participant_wallet": participant.get("wallet_address"),
                "wallet_status": participant.get("wallet_status", "missing"),
                "amount": amount,
                "reference": reference,
                "canonical": True,
                "generated_by": "generate_solana_pay_requests.py",
                "pay_url": pay_url,
                "qr_payload": pay_url,
                "memo": memo,
            }
        )

    if not requests:
        payload = response(
            "warning",
            "No reimbursing participants required payment requests",
            ["close_bill_if_no_balance_due"],
            [],
            {"requests": []},
        )
        emit(payload, args.output_file)
        return

    status = "success" if not missing_wallet_participants else "warning"
    summary = f"Generated {len(requests)} Solana Pay requests"
    next_actions = ["publish_group_payment_requests", "watch_bill_status"]
    if missing_wallet_participants:
        next_actions.append("request_optional_wallet_binding")
    payload = response(
        status,
        summary,
        next_actions,
        [args.output_file] if args.output_file else [],
        {
            "bill_id": args.bill_id,
            "recipient_wallet": args.recipient_wallet,
            "token_symbol": args.token_symbol,
            "token_mint": args.token_mint,
            "requests": requests,
            "missing_wallet_participants": missing_wallet_participants,
        },
    )
    emit(payload, args.output_file)


if __name__ == "__main__":
    main()
