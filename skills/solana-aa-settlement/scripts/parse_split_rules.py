import argparse
import re

from common import decimalize, emit, normalize_identifier, response


COUNT_PATTERN = re.compile(r"(\d+)\s*(people|persons|participants?)", re.IGNORECASE)
LEADING_COUNT_PREFIX = re.compile(r"^\s*\d+\s*(people|persons|participants?)\s*,\s*", re.IGNORECASE)
EXCLUDE_PATTERN = re.compile(r"(?:excluding|except)\s+([A-Za-z][A-Za-z0-9_\-\s,]+)", re.IGNORECASE)
ADJUST_PATTERN = re.compile(r"([A-Za-z][A-Za-z0-9_\-\s,]*?|I(?:\s*,\s*[A-Za-z][A-Za-z0-9_\-\s]*)*(?:\s+and\s+[A-Za-z][A-Za-z0-9_\-\s]*)*)\s+pay(?:s)?\s+(\d+(?:\.\d+)?)\s+(more|less)", re.IGNORECASE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Parse freeform split instructions into structured rules.")
    parser.add_argument("--rule-text", required=True)
    parser.add_argument("--payer-id", default="payer")
    parser.add_argument("--output-file", default=None)
    return parser


def parse_subjects(fragment: str, payer_id: str) -> list[str]:
    normalized_fragment = re.sub(r"\s+and\s+", ",", fragment, flags=re.IGNORECASE)
    subjects = []
    for part in normalized_fragment.split(","):
        value = part.strip()
        if not value:
            continue
        if value.lower() == "i":
            subjects.append(normalize_identifier(payer_id))
        else:
            subjects.append(normalize_identifier(value))
    return subjects


def main() -> None:
    args = build_parser().parse_args()
    text = args.rule_text.strip()

    participant_count = None
    count_match = COUNT_PATTERN.search(text)
    if count_match:
        participant_count = int(count_match.group(1))

    adjustments = []
    seen_adjustments = set()
    adjustment_text = LEADING_COUNT_PREFIX.sub("", text)
    for match in ADJUST_PATTERN.finditer(adjustment_text):
        subject_text = match.group(1)
        amount = decimalize(match.group(2))
        direction = match.group(3).lower()
        delta = amount if direction == "more" else -amount
        for participant_id in parse_subjects(subject_text, args.payer_id):
            key = (participant_id, f"{delta:.2f}")
            if key in seen_adjustments:
                continue
            seen_adjustments.add(key)
            adjustments.append(
                {
                    "participant_id": participant_id,
                    "delta_amount": f"{delta:.2f}",
                }
            )

    excluded = []
    exclude_match = EXCLUDE_PATTERN.search(text)
    if exclude_match:
        for part in exclude_match.group(1).split(","):
            value = part.strip()
            if value:
                excluded.append(normalize_identifier(value))

    if participant_count is None and not adjustments and not excluded:
        payload = response(
            "warning",
            "Could not infer participant count or split adjustments",
            ["ask_user_to_restate_split_rules"],
            [],
            {"raw_text": text},
        )
        emit(payload, args.output_file)
        return

    payload = response(
        "success",
        "Parsed split rules",
        ["build_split_plan"],
        [args.output_file] if args.output_file else [],
        {
            "participant_count": participant_count,
            "excluded_participants": excluded,
            "adjustments": adjustments,
            "raw_text": text,
        },
    )
    emit(payload, args.output_file)


if __name__ == "__main__":
    main()
