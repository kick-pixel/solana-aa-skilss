import argparse
from decimal import Decimal

from common import decimalize, emit, money_string, response, read_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Match observed payments against generated Solana Pay requests.")
    parser.add_argument("--requests-file", required=True)
    parser.add_argument("--payments-file", required=True)
    parser.add_argument("--output-file", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    requests_payload = read_json(args.requests_file).get("data", {})
    payments = read_json(args.payments_file)
    if isinstance(payments, dict):
        payments = [payments]

    payments_by_reference = {}
    for payment in payments:
        payments_by_reference.setdefault(payment.get("reference"), []).append(payment)

    participant_statuses = []
    total_due = Decimal("0")
    total_paid = Decimal("0")

    for request in requests_payload.get("requests", []):
        requested_amount = decimalize(request["amount"])
        total_due += requested_amount
        matched = payments_by_reference.get(request["reference"], [])
        paid_amount = sum(decimalize(item.get("amount", "0")) for item in matched)
        total_paid += min(paid_amount, requested_amount)
        if paid_amount >= requested_amount:
            request_status = "paid"
        elif paid_amount > 0:
            request_status = "underpaid"
        else:
            request_status = "pending"
        participant_statuses.append(
            {
                "participant_id": request["participant_id"],
                "request_status": request_status,
                "paid_amount": money_string(min(paid_amount, requested_amount)),
                "requested_amount": money_string(requested_amount),
                "reference": request["reference"],
            }
        )

    if total_due == Decimal("0"):
        bill_status = "paid"
    elif total_paid == Decimal("0"):
        bill_status = "payment_requests_generated"
    elif total_paid < total_due:
        bill_status = "partially_paid"
    else:
        bill_status = "paid"

    remaining = total_due - total_paid
    next_actions = ["close_bill"] if bill_status == "paid" else ["notify_group_status", "send_payment_reminders"]
    payload = response(
        "success",
        f"Bill status is {bill_status}",
        next_actions,
        [args.output_file] if args.output_file else [],
        {
            "bill_status": bill_status,
            "total_due": money_string(total_due),
            "total_paid": money_string(total_paid),
            "remaining_due": money_string(remaining),
            "participant_statuses": participant_statuses,
        },
    )
    emit(payload, args.output_file)


if __name__ == "__main__":
    main()
