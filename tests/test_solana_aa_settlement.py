import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "solana-aa-settlement"
SCRIPTS = ROOT / "skills" / "solana-aa-settlement" / "scripts"
PYTHON = sys.executable
TMP_ROOT = ROOT / "tests" / ".tmp"
CLAUDE_WRAPPER_SKILL = ROOT / ".claude" / "skills" / "solana-usdc-aa-bill" / "SKILL.md"


def run_script(script_name: str, args: list[str]) -> dict:
    command = [PYTHON, str(SCRIPTS / script_name), *args]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(
            f"{script_name} failed with code {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"{script_name} did not emit valid JSON\nSTDOUT:\n{result.stdout}"
        ) from exc


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def make_workdir(name: str) -> Path:
    path = TMP_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_happy_path() -> None:
    tmp_dir = make_workdir("happy_path")
    fetch_out = tmp_dir / "fetch.json"
    ranked_out = tmp_dir / "ranked.json"
    rules_out = tmp_dir / "rules.json"
    plan_out = tmp_dir / "plan.json"
    resolved_out = tmp_dir / "resolved.json"
    requests_out = tmp_dir / "requests.json"
    payments_out = tmp_dir / "payments.json"
    status_out = tmp_dir / "status.json"

    fetch = run_script(
        "fetch_recent_transfers.py",
        [
            "--input-file",
            str(FIXTURES / "wallet_activity_artifact.json"),
            "--wallet-address",
            "alice-wallet",
            "--token",
            "USDC",
            "--lookback-minutes",
            "180",
            "--now",
            "2026-03-16T12:00:00Z",
            "--output-file",
            str(fetch_out),
        ],
    )
    assert_equal(fetch["status"], "success", "fetch_recent_transfers status")
    assert_equal(fetch["data"]["count"], 3, "fetch_recent_transfers count")

    ranked = run_script(
        "rank_expense_candidates.py",
        [
            "--input-file",
            str(fetch_out),
            "--message-text",
            "help me split this dinner",
            "--now",
            "2026-03-16T12:00:00Z",
            "--output-file",
            str(ranked_out),
        ],
    )
    assert_equal(ranked["status"], "success", "rank_expense_candidates status")
    assert_equal(
        len(ranked["data"]["candidates"]),
        2,
        "ranked candidate count after signature collapse",
    )
    assert_equal(
        ranked["data"]["candidates"][0]["signature"],
        "sig-dinner",
        "top-ranked candidate signature",
    )
    assert_equal(
        ranked["data"]["candidates"][0]["instruction_count"],
        2,
        "collapsed instruction count",
    )

    rule_text = (FIXTURES / "rule_text_valid.txt").read_text(encoding="utf-8")
    parsed = run_script(
        "parse_split_rules.py",
        [
            "--rule-text",
            rule_text,
            "--payer-id",
            "alice",
            "--output-file",
            str(rules_out),
        ],
    )
    assert_equal(parsed["status"], "success", "parse_split_rules status")
    assert_equal(len(parsed["data"]["adjustments"]), 2, "parsed adjustment count")

    plan = run_script(
        "build_split_plan.py",
        [
            "--bill-amount",
            "280",
            "--parsed-rules-file",
            str(rules_out),
            "--participants-file",
            str(FIXTURES / "participants.json"),
            "--payer-id",
            "alice",
            "--output-file",
            str(plan_out),
        ],
    )
    assert_equal(plan["status"], "success", "build_split_plan status")
    assert_equal(
        plan["data"]["participant_count"], 5, "participant count in split plan"
    )
    assert_true(
        "chat_summary_text" in plan["data"],
        "split plan should expose chat-friendly summary text",
    )
    assert_true(
        "|" not in plan["data"]["chat_summary_text"],
        "chat-friendly split summary should avoid markdown table syntax",
    )

    resolved = run_script(
        "resolve_participant_wallets.py",
        [
            "--split-plan-file",
            str(plan_out),
            "--wallet-book-file",
            str(FIXTURES / "wallets.json"),
            "--output-file",
            str(resolved_out),
        ],
    )
    assert_equal(resolved["status"], "success", "resolve_participant_wallets status")

    requests = run_script(
        "generate_solana_pay_requests.py",
        [
            "--wallet-resolution-file",
            str(resolved_out),
            "--recipient-wallet",
            "alice-wallet",
            "--bill-id",
            "bill-001",
            "--output-file",
            str(requests_out),
        ],
    )
    assert_equal(requests["status"], "success", "generate_solana_pay_requests status")
    request_items = requests["data"]["requests"]
    assert_equal(len(request_items), 4, "generated reimbursement request count")
    assert_equal(
        len({item["reference"] for item in request_items}),
        4,
        "request references should be unique",
    )

    payments_payload = [
        {
            "reference": request_items[0]["reference"],
            "amount": request_items[0]["amount"],
            "payer_wallet": request_items[0]["participant_wallet"],
            "signature": "payment-1",
            "confirmed_at": "2026-03-16T12:05:00Z",
        }
    ]
    payments_out.write_text(
        json.dumps(payments_payload, ensure_ascii=True, indent=2), encoding="utf-8"
    )

    status = run_script(
        "watch_bill_status.py",
        [
            "--requests-file",
            str(requests_out),
            "--payments-file",
            str(payments_out),
            "--output-file",
            str(status_out),
        ],
    )
    assert_equal(status["status"], "success", "watch_bill_status status")
    assert_equal(
        status["data"]["bill_status"], "partially_paid", "bill status after one payment"
    )


def test_unknown_adjustment_participant() -> None:
    tmp_dir = make_workdir("unknown_adjustment")
    rules_out = tmp_dir / "rules.json"
    rule_text = (FIXTURES / "rule_text_unknown_participant.txt").read_text(
        encoding="utf-8"
    )

    run_script(
        "parse_split_rules.py",
        [
            "--rule-text",
            rule_text,
            "--payer-id",
            "alice",
            "--output-file",
            str(rules_out),
        ],
    )

    result = run_script(
        "build_split_plan.py",
        [
            "--bill-amount",
            "120",
            "--parsed-rules-file",
            str(rules_out),
            "--participants-file",
            str(FIXTURES / "participants.json"),
            "--payer-id",
            "alice",
        ],
    )
    assert_equal(
        result["status"], "error", "unknown participant should fail split plan"
    )
    assert_true(
        "frank" in result["data"]["unknown_adjustment_participants"],
        "unknown participant should be reported",
    )


def test_manual_bill_fallback() -> None:
    tmp_dir = make_workdir("manual_fallback")
    manual_out = tmp_dir / "manual.json"
    rules_out = tmp_dir / "rules.json"
    plan_out = tmp_dir / "plan.json"

    manual = run_script(
        "create_manual_bill_context.py",
        [
            "--bill-amount",
            "268",
            "--token-symbol",
            "USDC",
            "--payer-id",
            "alice",
            "--source-mode",
            "fallback",
            "--note",
            "manual fallback after transaction lookup failure",
            "--output-file",
            str(manual_out),
        ],
    )
    assert_equal(manual["status"], "success", "create_manual_bill_context status")
    assert_equal(
        manual["data"]["source_mode"], "fallback", "manual fallback source mode"
    )

    rule_text = (FIXTURES / "rule_text_valid.txt").read_text(encoding="utf-8")
    parsed = run_script(
        "parse_split_rules.py",
        [
            "--rule-text",
            rule_text,
            "--payer-id",
            "alice",
            "--output-file",
            str(rules_out),
        ],
    )
    assert_equal(parsed["status"], "success", "manual fallback parse status")

    plan = run_script(
        "build_split_plan.py",
        [
            "--bill-amount",
            manual["data"]["bill_amount"],
            "--parsed-rules-file",
            str(rules_out),
            "--participants-file",
            str(FIXTURES / "participants.json"),
            "--payer-id",
            manual["data"]["payer_id"],
            "--output-file",
            str(plan_out),
        ],
    )
    assert_equal(plan["status"], "success", "manual fallback split plan status")
    assert_equal(plan["data"]["bill_amount"], "268.00", "manual fallback bill amount")


def test_request_generation_without_participant_wallets() -> None:
    tmp_dir = make_workdir("no_wallets")
    plan_out = tmp_dir / "plan.json"
    resolved_out = tmp_dir / "resolved.json"
    requests_out = tmp_dir / "requests.json"

    rule_text = (FIXTURES / "rule_text_valid.txt").read_text(encoding="utf-8")
    rules_out = tmp_dir / "rules.json"
    run_script(
        "parse_split_rules.py",
        [
            "--rule-text",
            rule_text,
            "--payer-id",
            "alice",
            "--output-file",
            str(rules_out),
        ],
    )

    run_script(
        "build_split_plan.py",
        [
            "--bill-amount",
            "280",
            "--parsed-rules-file",
            str(rules_out),
            "--participants-file",
            str(FIXTURES / "participants.json"),
            "--payer-id",
            "alice",
            "--output-file",
            str(plan_out),
        ],
    )

    empty_wallets = tmp_dir / "empty_wallets.json"
    empty_wallets.write_text("{}", encoding="utf-8")

    resolved = run_script(
        "resolve_participant_wallets.py",
        [
            "--split-plan-file",
            str(plan_out),
            "--wallet-book-file",
            str(empty_wallets),
            "--output-file",
            str(resolved_out),
        ],
    )
    assert_equal(
        resolved["status"], "warning", "missing participant wallets should be a warning"
    )
    assert_true(
        len(resolved["data"]["missing_wallet_participants"]) == 4,
        "all reimbursing participants should be marked missing",
    )

    requests = run_script(
        "generate_solana_pay_requests.py",
        [
            "--wallet-resolution-file",
            str(resolved_out),
            "--recipient-wallet",
            "alice-wallet",
            "--bill-id",
            "bill-no-wallets",
            "--output-file",
            str(requests_out),
        ],
    )
    assert_equal(
        requests["status"],
        "warning",
        "request generation should still succeed with a warning when participant wallets are missing",
    )
    assert_equal(
        len(requests["data"]["requests"]),
        4,
        "requests should still be generated for all reimbursing participants",
    )
    assert_true(
        all(
            item["participant_wallet"] is None for item in requests["data"]["requests"]
        ),
        "participant wallets should remain optional metadata",
    )


def test_render_payment_requests_default_qr_output() -> None:
    tmp_dir = make_workdir("render_requests")
    requests_out = tmp_dir / "requests.json"
    render_out = tmp_dir / "render_result.json"
    render_dir = tmp_dir / "rendered"

    payload = {
        "data": {
            "bill_id": "bill-render",
            "recipient_wallet": "alice-wallet",
            "requests": [
                {
                    "request_id": "bill-render:bob",
                    "participant_id": "bob",
                    "display_name": "Bob",
                    "participant_wallet": None,
                    "wallet_status": "missing",
                    "amount": "25.00",
                    "reference": "7D6GiQ1RybCd492pphWcC7ra3yySjVaZErqqpoGdHXAM",
                    "pay_url": "solana:alice-wallet?amount=25.00&spl-token=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&reference=7D6GiQ1RybCd492pphWcC7ra3yySjVaZErqqpoGdHXAM&label=AA+Settlement&message=Reimburse+Bob&memo=bill%3Abill-render%3Abob",
                    "qr_payload": "solana:alice-wallet?amount=25.00",
                    "memo": "bill:bill-render:bob",
                }
            ],
        }
    }
    requests_out.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8"
    )

    rendered = run_script(
        "render_payment_requests.py",
        [
            "--input-file",
            str(requests_out),
            "--output-dir",
            str(render_dir),
            "--output-file",
            str(render_out),
        ],
    )
    assert_equal(rendered["status"], "success", "render_payment_requests status")
    assert_equal(
        rendered["data"]["qr_mode"],
        "remote_url",
        "default qr mode should produce visible qr output",
    )
    assert_true(
        bool(rendered["data"]["request_views"][0]["qr_image_src"]),
        "default render output should expose a QR image source",
    )
    qr_media = rendered["data"]["request_views"][0]["qr_sendable_media"]
    assert_equal(
        qr_media["type"], "image", "request view should expose image media metadata"
    )
    assert_equal(
        qr_media["transport_hint"],
        "sendPhoto",
        "request view should expose Telegram image send hint",
    )
    assert_equal(
        qr_media["source"],
        rendered["data"]["request_views"][0]["qr_image_src"],
        "media source should match qr image source",
    )
    assert_equal(
        len(rendered["data"]["outbound_media"]),
        1,
        "render output should expose outbound media entries",
    )
    assert_equal(
        rendered["data"]["outbound_media"][0]["request_id"],
        "bill-render:bob",
        "outbound media should be tied to request id",
    )
    shareable_link = rendered["data"]["shareable_links"][0]
    assert_equal(
        shareable_link["type"],
        "solana_pay_url",
        "render output should expose explicit payment link metadata",
    )
    assert_equal(
        shareable_link["url"],
        payload["data"]["requests"][0]["pay_url"],
        "shareable payment link should match pay_url",
    )
    assert_equal(
        len(rendered["data"]["shareable_links"]),
        1,
        "render output should expose top-level shareable payment links",
    )
    assert_equal(
        rendered["data"]["shareable_links"][0]["request_id"],
        "bill-render:bob",
        "shareable link should be tied to request id",
    )
    assert_true(
        "chat_share_text" in rendered["data"],
        "render output should expose chat-friendly share text",
    )
    assert_true(
        "|" not in rendered["data"]["chat_share_text"],
        "chat-friendly payment share text should avoid markdown table syntax",
    )
    assert_true(
        "solana:" not in rendered["data"]["chat_share_text"],
        "chat-friendly payment share text should not leak the raw pay url",
    )
    assert_true(
        payload["data"]["requests"][0]["reference"]
        not in rendered["data"]["chat_share_text"],
        "chat-friendly payment share text should not leak the reference",
    )
    assert_true(
        rendered["data"]["request_views"][0]["qr_sendable_media"]["source"]
        not in rendered["data"]["chat_share_text"],
        "chat-friendly payment share text should not print QR paths or URLs",
    )
    public_view = rendered["data"]["public_request_views"][0]
    assert_true(
        "reference" not in public_view,
        "public request view should not expose reference",
    )
    assert_true(
        "pay_url" not in public_view,
        "public request view should not expose raw pay url",
    )
    html_file = Path(rendered["data"]["rendered_files"]["html"])
    markdown_file = Path(rendered["data"]["rendered_files"]["markdown"])
    html_text = html_file.read_text(encoding="utf-8")
    markdown_text = markdown_file.read_text(encoding="utf-8")
    assert_true(
        "Open in wallet from a compatible runtime" in html_text,
        "html output should expose a wallet-open action",
    )
    assert_true(
        "OpenClaw-friendly remote image URLs" in html_text,
        "html output should explain remote QR preference for chat runtimes",
    )
    assert_true(
        "prefer-local-qr" not in html_text,
        "html output should not recommend local QR fallback in OpenClaw-oriented flows",
    )
    assert_true(
        "Open QR image" in html_text,
        "html output should expose a clickable QR image link",
    )
    assert_true(
        "Reference:" not in markdown_text,
        "markdown output should hide reference by default",
    )
    assert_true(
        "![QR code for Bob](https://api.qrserver.com/" in markdown_text,
        "markdown output should expose an embeddable QR image link",
    )
    assert_true(
        "solana:alice-wallet?amount=25.00&spl-token=" not in markdown_text,
        "markdown output should hide raw pay url by default",
    )
    assert_true(
        "Reference:" not in html_text,
        "html output should hide reference by default",
    )
    assert_true(
        "Copy link" not in html_text,
        "html output should hide raw link copy actions by default",
    )


def test_render_payment_requests_debug_view_shows_internal_fields() -> None:
    tmp_dir = make_workdir("render_requests_debug")
    requests_out = tmp_dir / "requests.json"
    render_out = tmp_dir / "render_result.json"

    payload = {
        "data": {
            "bill_id": "bill-debug",
            "recipient_wallet": "alice-wallet",
            "requests": [
                {
                    "request_id": "bill-debug:bob",
                    "participant_id": "bob",
                    "display_name": "Bob",
                    "participant_wallet": None,
                    "wallet_status": "missing",
                    "amount": "25.00",
                    "reference": "7D6GiQ1RybCd492pphWcC7ra3yySjVaZErqqpoGdHXAM",
                    "pay_url": "solana:alice-wallet?amount=25.00&spl-token=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&reference=7D6GiQ1RybCd492pphWcC7ra3yySjVaZErqqpoGdHXAM&label=AA+Settlement&message=Reimburse+Bob&memo=bill%3Abill-debug%3Abob",
                    "qr_payload": "solana:alice-wallet?amount=25.00",
                    "memo": "bill:bill-debug:bob",
                }
            ],
        }
    }
    requests_out.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8"
    )

    rendered = run_script(
        "render_payment_requests.py",
        [
            "--input-file",
            str(requests_out),
            "--debug-view",
            "--output-file",
            str(render_out),
        ],
    )
    debug_view = rendered["data"]["request_views"][0]
    assert_true(
        "reference" in debug_view,
        "debug request view should retain internal reference",
    )
    assert_true(
        "pay_url" in debug_view,
        "debug request view should retain internal pay url",
    )
    assert_true(
        debug_view["pay_url"] in rendered["data"]["chat_share_text"],
        "debug chat share text should expose raw pay url for operators",
    )


def test_render_payment_requests_rejects_noncanonical_pay_url() -> None:
    tmp_dir = make_workdir("render_requests_invalid")
    requests_out = tmp_dir / "requests.json"

    payload = {
        "data": {
            "bill_id": "bill-invalid",
            "recipient_wallet": "alice-wallet",
            "requests": [
                {
                    "request_id": "bill-invalid:bob",
                    "participant_id": "bob",
                    "display_name": "Bob",
                    "amount": "25.00",
                    "reference": "AA-DINNER-001-BLOB",
                    "pay_url": "solana:alice-wallet?amount=25.00&token=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&reference=AA-DINNER-001-BLOB&label=AA+Settlement",
                    "memo": "bill:bill-invalid:bob",
                }
            ],
        }
    }
    requests_out.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8"
    )

    rendered = run_script(
        "render_payment_requests.py",
        [
            "--input-file",
            str(requests_out),
        ],
    )
    assert_equal(
        rendered["status"],
        "error",
        "render_payment_requests should reject noncanonical requests",
    )
    assert_true(
        "reject_invalid_requests" in rendered["next_actions"],
        "render_payment_requests should instruct callers to regenerate invalid requests",
    )
    assert_true(
        rendered["data"]["validations"]["bill-invalid:bob"],
        "invalid request should include validation issues",
    )


def test_render_payment_requests_help_prefers_openclaw_remote_qr_language() -> None:
    command = [PYTHON, str(SCRIPTS / "render_payment_requests.py"), "--help"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert_equal(result.returncode, 0, "render_payment_requests --help exit code")
    assert_true(
        "OpenClaw-friendly remote QR" in result.stdout,
        "help output should describe remote QR defaults for OpenClaw-style hosts",
    )
    assert_true(
        "Telegram compatibility" not in result.stdout,
        "help output should not frame remote QR defaults as Telegram-only guidance",
    )


def test_claude_wrapper_forbids_handcrafted_links_and_local_qr_text() -> None:
    wrapper = CLAUDE_WRAPPER_SKILL.read_text(encoding="utf-8")
    assert_true(
        "Do not handcraft Solana Pay links" in wrapper,
        "Claude wrapper should explicitly forbid handcrafted Solana Pay links",
    )
    assert_true(
        "Use `spl-token`, never `mint`" in wrapper,
        "Claude wrapper should explicitly forbid the noncanonical mint= parameter",
    )
    assert_true(
        "Do not send a local filesystem path like `/home/admin/.openclaw/workspace/bob_payment_qr.png` as user-visible text"
        in wrapper,
        "Claude wrapper should explicitly forbid exposing local QR file paths as chat text",
    )
    assert_true(
        "Use `data.outbound_media` or `data.request_views[].qr_sendable_media` for Telegram/OpenClaw image delivery"
        in wrapper,
        "Claude wrapper should direct hosts to the structured QR media fields",
    )
    assert_true(
        "If canonical scripts have not been run yet, do not output any `solana:` URI"
        in wrapper,
        "Claude wrapper should forbid raw payment links before canonical generation",
    )
    assert_true(
        "Treat `token=` as invalid; canonical Solana Pay links use `spl-token=`"
        in wrapper,
        "Claude wrapper should explicitly reject noncanonical token= links",
    )
    assert_true(
        "Treat human-readable references like `AA-DINNER-001-BLOB` as invalid"
        in wrapper,
        "Claude wrapper should explicitly reject handcrafted references",
    )
    assert_true(
        "If `data.outbound_media` exists, send that media first and do not fall back to `chat_share_text` or local path text"
        in wrapper,
        "Claude wrapper should make outbound_media mandatory-first for host delivery",
    )


def test_fetcher_error_shape() -> None:
    result = run_script(
        "fetch_solana_wallet_activity.py",
        [
            "--rpc-url",
            "https://127.0.0.1:1",
            "--wallet-address",
            "test-wallet",
            "--limit",
            "1",
            "--request-timeout-seconds",
            "1",
            "--max-retries",
            "0",
            "--max-normalized-transfers",
            "1",
        ],
    )
    assert_equal(
        result["status"], "error", "RPC failure should return structured error"
    )
    assert_true(
        "root_cause_hint" in result["data"],
        "RPC failure should include root cause hint",
    )


def test_fetcher_curl_error_shape() -> None:
    if not (shutil.which("curl.exe") or shutil.which("curl")):
        print("SKIP test_fetcher_curl_error_shape: curl not available")
        return
    result = run_script(
        "fetch_solana_wallet_activity.py",
        [
            "--transport",
            "curl",
            "--rpc-url",
            "https://127.0.0.1:1",
            "--wallet-address",
            "test-wallet",
            "--limit",
            "1",
            "--request-timeout-seconds",
            "1",
            "--max-retries",
            "0",
            "--max-normalized-transfers",
            "1",
        ],
    )
    assert_equal(
        result["status"],
        "error",
        "curl transport failure should return structured error",
    )
    assert_true(
        "root_cause_hint" in result["data"],
        "curl transport failure should include root cause hint",
    )


def main() -> None:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    tests = [
        test_happy_path,
        test_unknown_adjustment_participant,
        test_manual_bill_fallback,
        test_request_generation_without_participant_wallets,
        test_render_payment_requests_default_qr_output,
        test_render_payment_requests_help_prefers_openclaw_remote_qr_language,
        test_claude_wrapper_forbids_handcrafted_links_and_local_qr_text,
        test_fetcher_error_shape,
        test_fetcher_curl_error_shape,
    ]
    failures = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failures.append((test.__name__, str(exc)))
            print(f"FAIL {test.__name__}: {exc}")

    if failures:
        print("\nRegression suite failed:")
        for name, message in failures:
            print(f"- {name}: {message}")
        raise SystemExit(1)

    print("\nAll solana-aa-settlement regression checks passed.")


if __name__ == "__main__":
    main()
