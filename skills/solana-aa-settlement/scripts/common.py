import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: str, payload: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


def response(
    status: str, summary: str, next_actions: list[str], artifacts: list[str], data: Any
) -> dict[str, Any]:
    return {
        "status": status,
        "summary": summary,
        "next_actions": next_actions,
        "artifacts": artifacts,
        "data": data,
    }


def emit(payload: dict[str, Any], output_file: str | None) -> None:
    if output_file:
        write_json(output_file, payload)
    print(json.dumps(payload, ensure_ascii=True, indent=2))


def utc_now(now_value: str | None = None) -> datetime:
    if not now_value:
        return datetime.now(timezone.utc)
    return parse_timestamp(now_value)


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def decimalize(value: Any) -> Decimal:
    return Decimal(str(value))


def money_string(value: Any, decimals: int = 2) -> str:
    quantum = Decimal("1").scaleb(-decimals)
    amount = decimalize(value)
    return format(amount.quantize(quantum), f".{decimals}f")


def round_down(value: Decimal, decimals: int = 2) -> Decimal:
    quantum = Decimal("1").scaleb(-decimals)
    return value.quantize(quantum, rounding=ROUND_DOWN)


def distribute_amounts(raw_amounts: list[Decimal], decimals: int = 2) -> list[Decimal]:
    rounded = [round_down(amount, decimals) for amount in raw_amounts]
    remainder = sum(raw_amounts) - sum(rounded)
    unit = Decimal("1").scaleb(-decimals)
    steps = int((remainder / unit).quantize(Decimal("1")))
    fractions = sorted(
        enumerate(raw_amounts),
        key=lambda item: (item[1] - rounded[item[0]], -item[0]),
        reverse=True,
    )
    for index, _ in fractions[:steps]:
        rounded[index] += unit
    return rounded


def normalize_identifier(value: str) -> str:
    cleaned = []
    for char in value.strip().lower():
        if char.isalnum() or char in {"-", "_"}:
            cleaned.append(char)
        elif char.isspace():
            cleaned.append("-")
    normalized = "".join(cleaned).strip("-")
    return normalized or "participant"


def load_participants(path: str) -> list[dict[str, Any]]:
    raw = read_json(path)
    participants = []
    for item in raw:
        if isinstance(item, str):
            participants.append(
                {"id": normalize_identifier(item), "display_name": item}
            )
        else:
            display_name = (
                item.get("display_name") or item.get("name") or item.get("id")
            )
            participant_id = item.get("id") or normalize_identifier(display_name)
            participants.append(
                {
                    "id": participant_id,
                    "display_name": display_name or participant_id,
                    **item,
                }
            )
    return participants


def load_wallet_book(path: str) -> dict[str, str]:
    raw = read_json(path)
    if isinstance(raw, dict):
        return {normalize_identifier(key): value for key, value in raw.items()}
    wallet_map = {}
    for item in raw:
        identifier = (
            item.get("id")
            or item.get("participant_id")
            or item.get("display_name")
            or item.get("name")
        )
        if not identifier:
            continue
        wallet = item.get("wallet_address") or item.get("wallet")
        if wallet:
            wallet_map[normalize_identifier(identifier)] = wallet
    return wallet_map


def base58_encode(raw_bytes: bytes) -> str:
    number = int.from_bytes(raw_bytes, "big")
    encoded = ""
    while number > 0:
        number, remainder = divmod(number, 58)
        encoded = BASE58_ALPHABET[remainder] + encoded
    leading_zeroes = len(raw_bytes) - len(raw_bytes.lstrip(b"\x00"))
    return ("1" * leading_zeroes) + (encoded or "1")


def random_reference() -> str:
    return base58_encode(os.urandom(32))


def is_canonical_reference(value: Any) -> bool:
    text = str(value or "").strip()
    return (
        bool(text)
        and set(text).issubset(set(BASE58_ALPHABET))
        and 32 <= len(text) <= 64
    )


def parse_solana_pay_url(value: Any) -> tuple[str, dict[str, list[str]]]:
    text = str(value or "").strip()
    if not text.startswith("solana:"):
        return "", {}
    parsed = urlparse(text)
    recipient = parsed.path
    if not recipient and parsed.netloc:
        recipient = parsed.netloc
    return recipient, parse_qs(parsed.query)


def validate_canonical_pay_url(value: Any, expected_reference: Any = None) -> list[str]:
    text = str(value or "").strip()
    issues = []
    recipient, params = parse_solana_pay_url(text)
    if not text.startswith("solana:"):
        return ["pay_url does not use the solana: scheme"]
    if not recipient:
        issues.append("pay_url is missing recipient wallet")
    if "amount" not in params:
        issues.append("pay_url is missing amount")
    if "reference" not in params:
        issues.append("pay_url is missing reference")
    if "spl-token" not in params:
        issues.append("pay_url is missing spl-token")
    if "token" in params:
        issues.append(
            "pay_url uses token; canonical Solana Pay links must use spl-token"
        )
    references = params.get("reference", [])
    if references:
        pay_url_reference = references[0]
        if not is_canonical_reference(pay_url_reference):
            issues.append(
                "pay_url reference is not a canonical base58-like Solana Pay reference"
            )
        expected_text = str(expected_reference or "").strip()
        if expected_text and pay_url_reference != expected_text:
            issues.append("pay_url reference does not match request reference")
    return issues


def window_start(now_value: datetime, lookback_minutes: int) -> datetime:
    return now_value - timedelta(minutes=lookback_minutes)
