import argparse
from collections import defaultdict
from decimal import Decimal

from common import (
    decimalize,
    distribute_amounts,
    emit,
    load_participants,
    money_string,
    response,
    round_down,
    read_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a split draft from parsed rules and a participant list."
    )
    parser.add_argument("--bill-amount", required=True)
    parser.add_argument("--parsed-rules-file", required=True)
    parser.add_argument("--participants-file", required=True)
    parser.add_argument("--payer-id", required=True)
    parser.add_argument("--output-file", default=None)
    return parser


def build_chat_summary_text(
    bill_amount: str, total_reimbursement: str, split_participants: list[dict]
) -> str:
    lines = [
        "AA split plan",
        f"Total bill: {bill_amount}",
        f"Total reimbursement due: {total_reimbursement}",
        "",
        "Participants:",
    ]
    for item in split_participants:
        role = "payer" if item["is_payer"] else "participant"
        lines.append(
            f"- {item['display_name']} ({role}): share {item['share_amount']}, reimbursement {item['reimbursement_amount']}"
        )
    return "\n".join(lines)


def main() -> None:
    args = build_parser().parse_args()
    bill_amount = decimalize(args.bill_amount)
    if bill_amount <= Decimal("0"):
        payload = response(
            "error",
            "Bill amount must be greater than zero",
            ["set_positive_bill_amount"],
            [],
            {"bill_amount": str(bill_amount)},
        )
        emit(payload, args.output_file)
        return

    rules = read_json(args.parsed_rules_file).get("data", {})
    participants = load_participants(args.participants_file)
    payer_id = args.payer_id

    excluded = set(rules.get("excluded_participants", []))
    eligible = [
        participant for participant in participants if participant["id"] not in excluded
    ]
    eligible_ids = {participant["id"] for participant in eligible}

    if not eligible:
        payload = response(
            "error",
            "No eligible participants remain after exclusions",
            ["ask_user_to_fix_participant_scope"],
            [],
            {"payer_id": payer_id},
        )
        emit(payload, args.output_file)
        return

    if not any(participant["id"] == payer_id for participant in eligible):
        payload = response(
            "error",
            "Payer must be included in the participant list",
            ["add_payer_to_participants"],
            [],
            {"payer_id": payer_id},
        )
        emit(payload, args.output_file)
        return

    unknown_adjustments = sorted(
        {
            item["participant_id"]
            for item in rules.get("adjustments", [])
            if item["participant_id"] not in eligible_ids
        }
    )
    if unknown_adjustments:
        payload = response(
            "error",
            "Split rules referenced participants who are not in the participant list",
            ["fix_adjustment_participants", "confirm_participant_aliases"],
            [],
            {"unknown_adjustment_participants": unknown_adjustments},
        )
        emit(payload, args.output_file)
        return

    participant_count = rules.get("participant_count")
    if participant_count is not None and participant_count != len(eligible):
        status = "warning"
        next_actions = ["confirm_participant_count"]
    else:
        status = "success"
        next_actions = ["confirm_split_plan"]

    adjustments_by_participant: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in rules.get("adjustments", []):
        adjustments_by_participant[item["participant_id"]] += decimalize(
            item["delta_amount"]
        )

    total_adjustment = sum(
        adjustments_by_participant.get(participant["id"], Decimal("0"))
        for participant in eligible
    )
    base_share_raw = (bill_amount - total_adjustment) / Decimal(len(eligible))

    raw_shares = [
        base_share_raw + adjustments_by_participant.get(participant["id"], Decimal("0"))
        for participant in eligible
    ]
    if any(value < 0 for value in raw_shares):
        payload = response(
            "error",
            "At least one participant ended up with a negative share",
            ["ask_user_to_adjust_split_rules"],
            [],
            {"raw_shares": [str(value) for value in raw_shares]},
        )
        emit(payload, args.output_file)
        return

    rounded_shares = distribute_amounts(raw_shares, decimals=2)
    split_participants = []
    for participant, share in zip(eligible, rounded_shares):
        is_payer = participant["id"] == payer_id
        split_participants.append(
            {
                "participant_id": participant["id"],
                "display_name": participant["display_name"],
                "is_payer": is_payer,
                "share_amount": money_string(share),
                "reimbursement_amount": money_string(
                    Decimal("0") if is_payer else share
                ),
            }
        )

    payer_share = next(
        decimalize(item["share_amount"])
        for item in split_participants
        if item["is_payer"]
    )
    total_reimbursement = round_down(bill_amount - payer_share, 2)
    total_reimbursement_text = money_string(total_reimbursement)
    chat_summary_text = build_chat_summary_text(
        money_string(bill_amount), total_reimbursement_text, split_participants
    )

    summary = f"Built split plan for {len(split_participants)} participants"
    payload = response(
        status,
        summary,
        next_actions,
        [args.output_file] if args.output_file else [],
        {
            "bill_amount": money_string(bill_amount),
            "payer_id": payer_id,
            "participant_count": len(split_participants),
            "total_reimbursement": total_reimbursement_text,
            "chat_summary_text": chat_summary_text,
            "participants": split_participants,
        },
    )
    emit(payload, args.output_file)


if __name__ == "__main__":
    main()
