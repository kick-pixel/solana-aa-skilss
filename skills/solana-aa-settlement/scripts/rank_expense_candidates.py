import argparse
import re
from collections import defaultdict
from decimal import Decimal

from common import decimalize, emit, parse_timestamp, read_json, response, utc_now


INTENT_KEYWORDS = {"dinner", "lunch", "restaurant", "cafe", "bar", "food", "meal", "bill", "split", "aa"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rank transfer candidates against a user expense request.")
    parser.add_argument("--input-file", required=True, help="JSON artifact produced by fetch_recent_transfers.py.")
    parser.add_argument("--message-text", required=True)
    parser.add_argument("--amount-hint", default=None)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--now", default=None)
    parser.add_argument("--output-file", default=None)
    return parser


def extract_keywords(text: str) -> set[str]:
    tokens = {token.lower() for token in re.findall(r"[A-Za-z]+", text)}
    return tokens & INTENT_KEYWORDS


def collapse_candidates(raw_candidates: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for candidate in raw_candidates:
        signature = candidate.get("signature") or "unknown-signature"
        grouped[signature].append(candidate)

    collapsed = []
    for signature, items in grouped.items():
        total_amount = sum(decimalize(item.get("amount", "0")) for item in items)
        timestamp = max(item.get("timestamp") for item in items)
        labels = [str(item.get("counterparty_label", "")).strip() for item in items if item.get("counterparty_label")]
        memos = [str(item.get("memo", "")).strip() for item in items if item.get("memo")]
        kinds = [str(item.get("kind", "")).strip() for item in items if item.get("kind")]
        counterparties = [str(item.get("counterparty", "")).strip() for item in items if item.get("counterparty")]
        token_symbol = next((item.get("token_symbol") for item in items if item.get("token_symbol")), None)
        collapsed.append(
            {
                "signature": signature,
                "timestamp": timestamp,
                "amount": f"{total_amount}",
                "token_symbol": token_symbol,
                "direction": next((item.get("direction") for item in items if item.get("direction")), None),
                "counterparty_label": ", ".join(sorted(set(labels))) or None,
                "memo": "; ".join(sorted(set(memos))) or None,
                "kind": ", ".join(sorted(set(kinds))) or None,
                "counterparty": ", ".join(sorted(set(counterparties))) or None,
                "instruction_count": len(items),
            }
        )
    return collapsed


def score_candidate(candidate: dict, message_text: str, now_value) -> tuple[float, list[str]]:
    score = 0.0
    reasons = []
    message_keywords = extract_keywords(message_text)
    candidate_text = " ".join(
        [
            str(candidate.get("counterparty_label", "")).lower(),
            str(candidate.get("memo", "")).lower(),
            str(candidate.get("kind", "")).lower(),
        ]
    )
    candidate_keywords = extract_keywords(candidate_text)
    shared_keywords = sorted(message_keywords & candidate_keywords)

    if candidate.get("direction") == "outgoing":
        score += 0.35
        reasons.append("recent outgoing payment")

    if shared_keywords:
        score += 0.22
        reasons.append(f"matched intent keywords: {', '.join(shared_keywords)}")

    if candidate.get("counterparty_label"):
        score += 0.12
        reasons.append("counterparty label is available")

    if candidate.get("memo"):
        score += 0.08
        reasons.append("memo is available")

    age_minutes = max((now_value - parse_timestamp(candidate["timestamp"])).total_seconds() / 60, 0)
    recency_score = max(0, 0.18 - min(age_minutes / 900, 0.18))
    if recency_score > 0:
        score += recency_score
        reasons.append("transaction is recent")

    amount = decimalize(candidate["amount"])
    if amount >= decimalize("100"):
        score += 0.18
        reasons.append("amount strongly fits a shared expense")
    elif amount >= decimalize("25"):
        score += 0.10
        reasons.append("amount plausibly fits a shared expense")
    elif amount >= decimalize("10"):
        score += 0.03
        reasons.append("amount is non-trivial")

    if candidate.get("instruction_count", 1) > 1:
        score += 0.04
        reasons.append("transaction includes multiple transfer instructions")

    return round(min(score, 0.99), 4), reasons


def main() -> None:
    args = build_parser().parse_args()
    artifact = read_json(args.input_file)
    raw_candidates = artifact.get("data", {}).get("transfers", artifact if isinstance(artifact, list) else [])
    candidates = collapse_candidates(raw_candidates)
    now_value = utc_now(args.now)
    amount_hint = decimalize(args.amount_hint) if args.amount_hint else None

    ranked = []
    for candidate in candidates:
        score, reasons = score_candidate(candidate, args.message_text, now_value)
        if amount_hint is not None:
            amount_gap = abs(decimalize(candidate["amount"]) - amount_hint)
            if amount_gap <= decimalize("1"):
                score += 0.15
                reasons.append("amount closely matched the provided hint")
            elif amount_gap <= decimalize("5"):
                score += 0.07
                reasons.append("amount loosely matched the provided hint")
        ranked.append(
            {
                "signature": candidate.get("signature"),
                "score": round(min(score, 0.99), 4),
                "timestamp": candidate.get("timestamp"),
                "amount": candidate.get("amount"),
                "token_symbol": candidate.get("token_symbol"),
                "counterparty_label": candidate.get("counterparty_label"),
                "instruction_count": candidate.get("instruction_count", 1),
                "reason_summary": reasons,
            }
        )

    ranked.sort(key=lambda item: (-item["score"], item["timestamp"]))
    ranked = ranked[: args.limit]

    if not ranked:
        payload = response(
            "error",
            "No ranked expense candidates were produced",
            ["ask_user_for_manual_transaction_selection"],
            [],
            {"candidates": []},
        )
        emit(payload, args.output_file)
        return

    status = "success" if ranked[0]["score"] >= 0.5 else "warning"
    summary = f"Ranked {len(ranked)} expense candidates"
    next_actions = ["ask_user_to_confirm_candidate"]
    payload = response(status, summary, next_actions, [args.output_file] if args.output_file else [], {"candidates": ranked})
    emit(payload, args.output_file)


if __name__ == "__main__":
    main()
