import argparse
import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from common import emit, isoformat_utc, money_string, response


DEFAULT_MAINNET_RPC = "https://api.mainnet.solana.com"
KNOWN_TOKEN_SYMBOLS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and normalize recent Solana wallet activity from JSON-RPC."
    )
    parser.add_argument("--rpc-url", default=DEFAULT_MAINNET_RPC)
    parser.add_argument("--wallet-address", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-normalized-transfers", type=int, default=50)
    parser.add_argument("--token-mint", default=None)
    parser.add_argument("--include-native", action="store_true")
    parser.add_argument("--before-signature", default=None)
    parser.add_argument("--request-timeout-seconds", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--transaction-delay-ms", type=int, default=350)
    parser.add_argument(
        "--transport", choices=["auto", "urllib", "curl"], default="auto"
    )
    parser.add_argument(
        "--http-header",
        action="append",
        default=[],
        help="Repeatable custom header in KEY=VALUE format for provider-specific auth.",
    )
    parser.add_argument("--output-file", default=None)
    return parser


def parse_headers(header_args: list[str]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    for item in header_args:
        if "=" not in item:
            raise ValueError(
                f"Invalid --http-header value: {item}. Expected KEY=VALUE."
            )
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Invalid --http-header key in: {item}")
        headers[key] = value
    return headers


def rpc_call_urllib(
    rpc_url: str,
    method: str,
    params: list[Any],
    timeout_seconds: int,
    max_retries: int,
    headers: dict[str, str],
) -> Any:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode("utf-8")
    request = urllib.request.Request(
        rpc_url, data=payload, headers=headers, method="POST"
    )
    attempts = 0
    while True:
        try:
            with urllib.request.urlopen(
                request, timeout=timeout_seconds
            ) as response_handle:
                response_json = json.loads(response_handle.read().decode("utf-8"))
            if "error" in response_json:
                raise RuntimeError(f"RPC error for {method}: {response_json['error']}")
            return response_json.get("result")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                raw_body = exc.read()
                if raw_body:
                    body = raw_body.decode("utf-8", errors="replace").strip()
            except Exception:
                body = ""
            if exc.code == 429 and attempts < max_retries:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                sleep_seconds = float(retry_after) if retry_after else 1 + attempts
                time.sleep(sleep_seconds)
                attempts += 1
                continue
            detail = f"HTTP {exc.code} {exc.reason}"
            if body:
                detail += f" | body: {body}"
            raise RuntimeError(f"RPC request failed for {method}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempts >= max_retries:
                raise RuntimeError(f"RPC request failed for {method}: {exc}") from exc
            time.sleep(1 + attempts)
            attempts += 1


def find_curl_binary() -> str | None:
    return shutil.which("curl.exe") or shutil.which("curl")


def rpc_call_curl(
    rpc_url: str,
    method: str,
    params: list[Any],
    timeout_seconds: int,
    max_retries: int,
    headers: dict[str, str],
) -> Any:
    curl_bin = find_curl_binary()
    if not curl_bin:
        raise RuntimeError("curl transport requested but curl executable was not found")

    # Validate RPC URL to prevent command injection
    if not isinstance(rpc_url, str) or not rpc_url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid RPC URL: {rpc_url}")

    # Validate method name (alphanumeric and underscores only)
    if not isinstance(method, str) or not re.match(r"^[a-zA-Z0-9_]+$", method):
        raise ValueError(f"Invalid RPC method name: {method}")

    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        ensure_ascii=True,
    )

    # Validate payload size
    MAX_PAYLOAD_SIZE = 10 * 1024 * 1024  # 10MB limit
    if len(payload.encode("utf-8")) > MAX_PAYLOAD_SIZE:
        raise ValueError(f"Payload exceeds maximum size of {MAX_PAYLOAD_SIZE} bytes")

    attempts = 0
    while True:
        command = [
            curl_bin,
            "--silent",
            "--show-error",
            "--fail-with-body",
            "-X",
            "POST",
            rpc_url,
            "--connect-timeout",
            str(timeout_seconds),
            "--max-time",
            str(timeout_seconds),
            "--data-binary",
            payload,
        ]
        for key, value in headers.items():
            # Validate header keys and values
            if not isinstance(key, str) or "\n" in key or "\r" in key:
                raise ValueError(f"Invalid HTTP header key: {key}")
            if not isinstance(value, str) or "\n" in value or "\r" in value:
                raise ValueError(f"Invalid HTTP header value for {key}")
            command.extend(["-H", f"{key}: {value}"])

        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        combined = " | ".join(part for part in [stderr, stdout] if part)

        if result.returncode == 0:
            try:
                response_json = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"curl transport returned non-JSON output for {method}: {combined}"
                ) from exc
            if "error" in response_json:
                raise RuntimeError(f"RPC error for {method}: {response_json['error']}")
            return response_json.get("result")

        if "429" in combined and attempts < max_retries:
            time.sleep(1 + attempts)
            attempts += 1
            continue

        raise RuntimeError(
            f"RPC request failed for {method}: {combined or f'curl exit code {result.returncode}'}"
        )


def rpc_call(
    rpc_url: str,
    method: str,
    params: list[Any],
    timeout_seconds: int,
    max_retries: int,
    headers: dict[str, str],
    transport: str,
) -> tuple[Any, str]:
    errors = []

    if transport in {"auto", "urllib"}:
        try:
            return rpc_call_urllib(
                rpc_url, method, params, timeout_seconds, max_retries, headers
            ), "urllib"
        except Exception as exc:
            errors.append(f"urllib: {exc}")
            if transport == "urllib":
                raise RuntimeError(errors[-1]) from exc

    if transport in {"auto", "curl"}:
        try:
            return rpc_call_curl(
                rpc_url, method, params, timeout_seconds, max_retries, headers
            ), "curl"
        except Exception as exc:
            errors.append(f"curl: {exc}")
            if transport == "curl":
                raise RuntimeError(errors[-1]) from exc

    raise RuntimeError(" ; ".join(errors) if errors else "No RPC transport succeeded")


def extract_memo(message: dict[str, Any]) -> str | None:
    for instruction in message.get("instructions", []):
        if instruction.get("program") == "spl-memo":
            parsed = instruction.get("parsed")
            if isinstance(parsed, str):
                return parsed
            if isinstance(parsed, dict):
                return parsed.get("memo") or parsed.get("text")
    return None


def instruction_iter(transaction: dict[str, Any]) -> list[dict[str, Any]]:
    message = transaction.get("transaction", {}).get("message", {})
    instructions = list(message.get("instructions", []))
    meta = transaction.get("meta", {})
    for inner in meta.get("innerInstructions", []):
        instructions.extend(inner.get("instructions", []))
    return instructions


def parse_token_amount(info: dict[str, Any]) -> str | None:
    token_amount = info.get("tokenAmount")
    if isinstance(token_amount, dict):
        if token_amount.get("uiAmountString") is not None:
            return str(token_amount["uiAmountString"])
        amount = token_amount.get("amount")
        decimals = int(token_amount.get("decimals", 0))
        if amount is not None:
            scaled = Decimal(str(amount)) / (Decimal(10) ** decimals)
            return (
                money_string(scaled, max(0, min(decimals, 9))).rstrip("0").rstrip(".")
                or "0"
            )
    amount = info.get("amount")
    if amount is not None:
        return str(amount)
    return None


def normalize_instruction(
    signature: str,
    timestamp: str,
    wallet_address: str,
    memo: str | None,
    instruction: dict[str, Any],
    token_mint_filter: str | None,
    include_native: bool,
) -> dict[str, Any] | None:
    program = instruction.get("program")
    parsed = instruction.get("parsed")
    if not isinstance(parsed, dict):
        return None
    instruction_type = parsed.get("type")
    info = parsed.get("info", {})

    if program == "spl-token" and instruction_type in {"transfer", "transferChecked"}:
        source = info.get("source")
        destination = info.get("destination")
        authority = info.get("authority") or info.get("owner")
        token_mint = info.get("mint")
        if token_mint_filter and token_mint != token_mint_filter:
            return None
        direction = None
        if source == wallet_address or authority == wallet_address:
            direction = "outgoing"
        elif destination == wallet_address:
            direction = "incoming"
        if not direction:
            return None
        amount = parse_token_amount(info)
        if amount is None:
            return None
        counterparty = destination if direction == "outgoing" else source
        return {
            "signature": signature,
            "timestamp": timestamp,
            "owner": wallet_address,
            "source": source,
            "destination": destination,
            "direction": direction,
            "amount": amount,
            "token_symbol": KNOWN_TOKEN_SYMBOLS.get(token_mint, token_mint or "TOKEN"),
            "token_mint": token_mint,
            "counterparty": counterparty,
            "counterparty_label": None,
            "memo": memo,
            "kind": instruction_type,
        }

    if include_native and program == "system" and instruction_type == "transfer":
        source = info.get("source")
        destination = info.get("destination")
        if source != wallet_address and destination != wallet_address:
            return None
        lamports = info.get("lamports")
        if lamports is None:
            return None
        direction = "outgoing" if source == wallet_address else "incoming"
        counterparty = destination if direction == "outgoing" else source
        amount = Decimal(str(lamports)) / Decimal("1000000000")
        return {
            "signature": signature,
            "timestamp": timestamp,
            "owner": wallet_address,
            "source": source,
            "destination": destination,
            "direction": direction,
            "amount": money_string(amount, 9).rstrip("0").rstrip(".") or "0",
            "token_symbol": "SOL",
            "token_mint": "",
            "counterparty": counterparty,
            "counterparty_label": None,
            "memo": memo,
            "kind": instruction_type,
        }

    return None


def append_unique_record(
    unique_records: list[dict[str, Any]],
    seen_keys: set[tuple[Any, ...]],
    record: dict[str, Any],
) -> bool:
    key = (
        record.get("signature"),
        record.get("source"),
        record.get("destination"),
        record.get("amount"),
        record.get("token_mint"),
        record.get("kind"),
    )
    if key in seen_keys:
        return False
    seen_keys.add(key)
    unique_records.append(record)
    return True


def main() -> None:
    args = build_parser().parse_args()

    try:
        headers = parse_headers(args.http_header)
        signature_params: dict[str, Any] = {"limit": args.limit}
        if args.before_signature:
            signature_params["before"] = args.before_signature

        signatures, transport_used = rpc_call(
            args.rpc_url,
            "getSignaturesForAddress",
            [args.wallet_address, signature_params],
            args.request_timeout_seconds,
            args.max_retries,
            headers,
            args.transport,
        )
        signatures = signatures or []
        normalized_records: list[dict[str, Any]] = []
        seen_keys: set[tuple[Any, ...]] = set()
        fetched_transactions = 0

        for index, signature_entry in enumerate(signatures):
            if (
                args.max_normalized_transfers
                and len(normalized_records) >= args.max_normalized_transfers
            ):
                break
            signature = signature_entry.get("signature")
            if not signature:
                continue
            if index > 0 and args.transaction_delay_ms > 0:
                time.sleep(args.transaction_delay_ms / 1000)
            transaction, tx_transport_used = rpc_call(
                args.rpc_url,
                "getTransaction",
                [
                    signature,
                    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
                ],
                args.request_timeout_seconds,
                args.max_retries,
                headers,
                args.transport,
            )
            transport_used = tx_transport_used if tx_transport_used else transport_used
            if not transaction:
                continue
            fetched_transactions += 1
            block_time = transaction.get("blockTime")
            if block_time is None:
                continue
            timestamp = isoformat_utc(
                datetime.fromtimestamp(block_time, tz=timezone.utc)
            )
            memo = extract_memo(transaction.get("transaction", {}).get("message", {}))
            for instruction in instruction_iter(transaction):
                normalized = normalize_instruction(
                    signature,
                    timestamp,
                    args.wallet_address,
                    memo,
                    instruction,
                    args.token_mint,
                    args.include_native,
                )
                if normalized is None:
                    continue
                append_unique_record(normalized_records, seen_keys, normalized)
                if (
                    args.max_normalized_transfers
                    and len(normalized_records) >= args.max_normalized_transfers
                ):
                    break

        normalized_records.sort(key=lambda item: item["timestamp"], reverse=True)

        status = "success" if normalized_records else "warning"
        summary = f"Fetched {len(normalized_records)} normalized wallet transfers from {fetched_transactions} transactions"
        next_actions = (
            ["filter_recent_transfers"]
            if normalized_records
            else ["expand_limit", "verify_rpc_wallet_activity"]
        )
        payload = response(
            status,
            summary,
            next_actions,
            [args.output_file] if args.output_file else [],
            {
                "wallet_address": args.wallet_address,
                "rpc_url": args.rpc_url,
                "transport_used": transport_used,
                "transaction_count": fetched_transactions,
                "max_normalized_transfers": args.max_normalized_transfers,
                "transfers": normalized_records,
            },
        )
    except Exception as exc:
        payload = response(
            "error",
            "Failed to fetch wallet activity from Solana mainnet RPC",
            ["retry_rpc_call", "switch_mainnet_rpc_provider", "try_curl_transport"],
            [],
            {
                "wallet_address": args.wallet_address,
                "rpc_url": args.rpc_url,
                "root_cause_hint": str(exc),
            },
        )

    emit(payload, args.output_file)


if __name__ == "__main__":
    main()
