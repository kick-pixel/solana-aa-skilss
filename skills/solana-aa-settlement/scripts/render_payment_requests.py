from __future__ import annotations

import argparse
import html
import importlib.util
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from common import (
    emit,
    is_canonical_reference,
    read_json,
    response,
    validate_canonical_pay_url,
)


UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
PLACEHOLDER_PATTERN = re.compile(r"^[\[【].*[\]】]$")
DEFAULT_REMOTE_QR_BASE = (
    "https://api.qrserver.com/v1/create-qr-code/?size=320x320&data="
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render canonical Solana Pay payment requests into HTML and Markdown for easier sharing and review."
    )
    parser.add_argument("--input-file", required=True)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write HTML/Markdown files. If not provided, only JSON output is returned without file generation.",
    )
    parser.add_argument("--html-name", default="payment_requests.html")
    parser.add_argument("--markdown-name", default="payment_requests.md")
    parser.add_argument("--qr-dir-name", default="qr")
    parser.add_argument(
        "--prefer-local-qr",
        action="store_true",
        help="Prefer local QR generation when qrcode library is available. Default uses OpenClaw-friendly remote QR URLs for chat-host display.",
    )
    parser.add_argument(
        "--debug-view",
        action="store_true",
        help="Expose internal reconciliation fields such as reference, memo, and raw Solana Pay links for operator debugging.",
    )
    parser.add_argument("--remote-qr-base", default=DEFAULT_REMOTE_QR_BASE)
    parser.add_argument("--output-file", default=None)
    return parser


def load_requests(payload: dict) -> tuple[dict, list[dict]]:
    data = payload.get("data", payload)
    recipient_wallet = data.get("recipient_wallet") or data.get("payer_wallet") or ""
    bill_id = data.get("bill_id") or "bill"
    requests = data.get("requests", [])
    return {
        "recipient_wallet": recipient_wallet,
        "bill_id": bill_id,
        "data": data,
    }, requests


def validate_request(item: dict) -> list[str]:
    issues = []
    reference = str(item.get("reference", "")).strip()
    if UUID_PATTERN.match(reference):
        issues.append("reference is UUID-like, not standard Solana Pay base58")
    elif not is_canonical_reference(reference):
        issues.append("reference is not a valid base58-like Solana Pay reference")

    participant_wallet = item.get("participant_wallet")
    if isinstance(participant_wallet, str) and PLACEHOLDER_PATTERN.match(
        participant_wallet.strip()
    ):
        issues.append("participant wallet is a placeholder string, not real metadata")

    issues.extend(validate_canonical_pay_url(item.get("pay_url", ""), reference))
    return issues


def has_local_qr_support() -> bool:
    return importlib.util.find_spec("qrcode") is not None


def generate_qr_assets(
    requests: list[dict],
    output_dir: Path,
    qr_dir_name: str,
    remote_qr_base: str,
    prefer_local_qr: bool,
) -> tuple[str, dict[str, dict[str, str]]]:
    qr_assets: dict[str, dict[str, str]] = {}

    if prefer_local_qr and has_local_qr_support() and output_dir.exists():
        import qrcode

        qr_dir = output_dir / qr_dir_name
        qr_dir.mkdir(parents=True, exist_ok=True)
        for item in requests:
            request_id = item.get("request_id", "request")
            png_name = f"{request_id.replace(':', '_')}.png"
            png_path = qr_dir / png_name
            image = qrcode.make(str(item.get("pay_url", "")))
            with png_path.open("wb") as handle:
                image.save(handle, "PNG")
            qr_assets[request_id] = {
                "mode": "local_png",
                "src": str(Path(qr_dir_name) / png_name).replace("\\", "/"),
            }
        return "local_png", qr_assets

    for item in requests:
        request_id = item.get("request_id", "request")
        qr_assets[request_id] = {
            "mode": "remote_url",
            "src": remote_qr_base + quote(str(item.get("pay_url", "")), safe=""),
        }
    return "remote_url", qr_assets


def build_sendable_media(
    item: dict, qr_asset: dict[str, str], output_dir: Optional[Path]
) -> dict | None:
    src = qr_asset.get("src")
    if not src:
        return None
    mode = qr_asset.get("mode")
    if mode == "local_png" and output_dir and output_dir.exists():
        source = str((output_dir / src).resolve())
        source_type = "path"
    else:
        source = src
        source_type = "url"
    display_name = (
        item.get("display_name")
        or item.get("participant_name")
        or item.get("participant_id")
        or "participant"
    )
    amount = item.get("amount")
    return {
        "type": "image",
        "transport_hint": "sendPhoto",
        "source": source,
        "source_type": source_type,
        "request_id": item.get("request_id"),
        "participant_id": item.get("participant_id"),
        "caption": f"{display_name} payment QR for {amount} via Solana Pay",
        "alt_text": f"QR code for {display_name} payment request",
    }


def build_shareable_payment_link(item: dict) -> dict | None:
    pay_url = str(item.get("pay_url", "")).strip()
    if not pay_url:
        return None
    display_name = (
        item.get("display_name")
        or item.get("participant_name")
        or item.get("participant_id")
        or "participant"
    )
    amount = item.get("amount")
    return {
        "type": "solana_pay_url",
        "url": pay_url,
        "request_id": item.get("request_id"),
        "participant_id": item.get("participant_id"),
        "display_text": f"Open {display_name}'s Solana Pay link for {amount}",
        "share_text": f"{display_name} payment link ({amount}): {pay_url}",
    }


def build_wallet_open_action() -> dict:
    return {
        "type": "wallet_open_action",
        "label": "Open in wallet from a compatible runtime",
    }


def build_chat_share_text(request_views: list[dict], debug_view: bool) -> str:
    lines = ["Payment requests"]
    for view in request_views:
        lines.append("")
        lines.append(
            f"{view.get('display_name')}: pay {view.get('amount')} via Solana Pay"
        )
        qr_media = view.get("qr_sendable_media") or {}
        wallet_open = view.get("wallet_open_action") or {}
        if debug_view and view.get("pay_url"):
            lines.append(f"Link: {view.get('pay_url')}")
        elif qr_media.get("source"):
            lines.append("Use the attached QR image to pay.")
        elif wallet_open.get("label"):
            lines.append(wallet_open["label"])
        else:
            lines.append("Open the payment request from a compatible wallet runtime.")
    return "\n".join(lines)


def build_request_views(
    requests: list[dict],
    validations: dict[str, list[str]],
    qr_assets: dict[str, dict[str, str]],
    output_dir: Optional[Path],
    debug_view: bool,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    request_views = []
    public_request_views = []
    outbound_media = []
    shareable_links = []
    for item in requests:
        request_id = item.get("request_id", "")
        qr_asset = qr_assets.get(request_id, {})
        sendable_media = build_sendable_media(item, qr_asset, output_dir)
        shareable_payment_link = build_shareable_payment_link(item)
        wallet_open_action = build_wallet_open_action()
        if sendable_media:
            outbound_media.append(sendable_media)
        if shareable_payment_link:
            shareable_links.append(shareable_payment_link)

        public_view = {
            "request_id": request_id,
            "participant_id": item.get("participant_id"),
            "display_name": item.get("display_name")
            or item.get("participant_name")
            or item.get("participant_id"),
            "amount": item.get("amount"),
            "qr_image_src": qr_asset.get("src"),
            "qr_mode": qr_asset.get("mode"),
            "qr_sendable_media": sendable_media,
            "wallet_open_action": wallet_open_action,
            "validation_issues": validations.get(request_id, []),
            "share_text": f"Pay {item.get('amount')} to {item.get('display_name') or item.get('participant_name') or item.get('participant_id')} via Solana Pay.",
        }
        request_view = dict(public_view)
        if debug_view:
            request_view.update(
                {
                    "reference": item.get("reference"),
                    "memo": item.get("memo"),
                    "pay_url": item.get("pay_url"),
                    "shareable_payment_link": shareable_payment_link,
                    "share_text": f"Pay {item.get('amount')} to {item.get('display_name') or item.get('participant_name') or item.get('participant_id')} via Solana Pay: {item.get('pay_url', '')}",
                }
            )
        request_views.append(request_view)
        public_request_views.append(public_view)
    return request_views, public_request_views, outbound_media, shareable_links


def to_markdown(
    meta: dict,
    request_views: list[dict],
    validations: dict[str, list[str]],
    qr_mode: str,
    debug_view: bool,
) -> str:
    lines = []
    lines.append(f"# Payment Requests: {meta['bill_id']}")
    lines.append("")
    lines.append(f"Recipient wallet: `{meta['recipient_wallet']}`")
    lines.append("")
    lines.append(f"QR mode: `{qr_mode}`")
    if qr_mode == "remote_url":
        lines.append(
            "QR previews are enabled through a remote image URL so chat clients can display a visible QR by default."
        )
        lines.append("")
    elif qr_mode == "none":
        lines.append(
            "No QR images were generated. Use `--prefer-local-qr` if you want local PNG files (requires qrcode library)."
        )
        lines.append("")
    for item in request_views:
        name = item.get("display_name") or item.get("participant_id") or "participant"
        request_id = item.get("request_id", "")
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"- Amount: `{item.get('amount')}`")
        if debug_view:
            lines.append(f"- Reference: `{item.get('reference')}`")
            lines.append(f"- Memo: `{item.get('memo')}`")
        issues = validations.get(request_id, [])
        if issues:
            lines.append("- Validation: `WARNING`")
            for issue in issues:
                lines.append(f"  - {issue}")
        else:
            lines.append("- Validation: `OK`")
        lines.append("")
        lines.append("Wallet action:")
        lines.append("")
        lines.append(f"- {item.get('wallet_open_action', {}).get('label')}")
        lines.append("")
        if debug_view and item.get("pay_url"):
            lines.append(f"[Open in wallet]({str(item.get('pay_url', ''))})")
            lines.append("")
            lines.append("```text")
            lines.append(str(item.get("pay_url", "")))
            lines.append("```")
            lines.append("")
        if item.get("qr_image_src"):
            lines.append(f"[Open QR image]({item['qr_image_src']})")
            lines.append("")
            lines.append(f"![QR code for {name}]({item['qr_image_src']})")
            lines.append("")
    lines.append("## Usage")
    lines.append("")
    lines.append(
        "- In chat runtimes, send the QR image via structured media instead of printing local file paths or raw Solana Pay links."
    )
    lines.append(
        "- If the wallet does not open from a compatible runtime, scan the QR image from a mobile wallet app."
    )
    lines.append(
        "- If the request has validation warnings, regenerate it before sending it to payers."
    )
    return "\n".join(lines) + "\n"


def to_html(
    meta: dict,
    request_views: list[dict],
    validations: dict[str, list[str]],
    qr_mode: str,
    debug_view: bool,
) -> str:
    cards = []
    for item in request_views:
        request_id = item.get("request_id", "")
        name = html.escape(
            str(item.get("display_name") or item.get("participant_id") or "participant")
        )
        pay_url = str(item.get("pay_url", ""))
        pay_url_html = html.escape(pay_url)
        issues = validations.get(request_id, [])
        issue_block = "".join(f"<li>{html.escape(issue)}</li>" for issue in issues)
        validation_html = (
            f"<div class='warn'><strong>Warnings</strong><ul>{issue_block}</ul></div>"
            if issues
            else "<div class='ok'>Validation OK</div>"
        )
        qr_src = item.get("qr_image_src")
        qr_link = (
            f"<a class='open secondary' href='{html.escape(qr_src)}' target='_blank' rel='noopener noreferrer'>Open QR image</a>"
            if qr_src
            else ""
        )
        qr_img = (
            f"<a class='qr-link' href='{html.escape(qr_src)}' target='_blank' rel='noopener noreferrer'><img class='qr' src='{html.escape(qr_src)}' alt='QR code for {name}' /></a>"
            if qr_src
            else "<div class='noqr'>No QR preview available for this request.</div>"
        )
        action_note = html.escape(
            item.get("wallet_open_action", {}).get(
                "label", "Open in wallet from a compatible runtime"
            )
        )
        actions = [f"<span class='action-note'>{action_note}</span>", qr_link]
        details = ""
        if debug_view and pay_url:
            phantom_link = f"https://phantom.app/ul/browse/{quote(pay_url, safe='')}"
            solflare_link = (
                f"https://solflare.com/ul/v1/browse/{quote(pay_url, safe='')}"
            )
            actions = [
                f"<a class='open' href='{pay_url_html}'>Open in wallet</a>",
                f"<a class='open secondary' href='{html.escape(phantom_link)}' target='_blank' rel='noopener noreferrer'>Open in Phantom</a>",
                f"<a class='open secondary' href='{html.escape(solflare_link)}' target='_blank' rel='noopener noreferrer'>Open in Solflare</a>",
                qr_link,
                f"<button onclick=\"copyText('{pay_url_html}')\">Copy link</button>",
            ]
            details = (
                f"<p><strong>Reference:</strong> <code>{html.escape(str(item.get('reference')))}</code></p>"
                f"<p><strong>Memo:</strong> <code>{html.escape(str(item.get('memo')))}</code></p>"
                f"<textarea readonly>{pay_url_html}</textarea>"
            )
        cards.append(
            f"""
            <section class="card">
              <h2>{name}</h2>
              <p><strong>Amount:</strong> {html.escape(str(item.get("amount")))}</p>
              {validation_html}
              <div class="actions">
                {" ".join(action for action in actions if action)}
              </div>
              {qr_img}
              {details}
            </section>
            """
        )
    if qr_mode == "local_png":
        qr_note = "QR images are generated locally."
    elif qr_mode == "remote_url":
        qr_note = "QR images are generated as OpenClaw-friendly remote image URLs so chat systems can display them by default."
    else:
        qr_note = "No QR images were generated. Use --prefer-local-qr if you want local PNG files (requires qrcode library)."
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Payment Requests {html.escape(meta["bill_id"])}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; background: #f6f4ee; color: #1f2328; }}
    h1 {{ margin-bottom: 8px; }}
    .card {{ background: white; border-radius: 16px; padding: 18px; margin: 18px 0; box-shadow: 0 8px 24px rgba(0,0,0,.08); }}
    .actions {{ display: flex; gap: 12px; margin: 12px 0; flex-wrap: wrap; align-items: center; }}
    .open, button {{ border: 0; border-radius: 999px; padding: 10px 16px; text-decoration: none; cursor: pointer; background: #0b6bcb; color: white; font: inherit; }}
    .secondary {{ background: #5b6472; }}
    textarea {{ width: 100%; min-height: 110px; margin-top: 12px; font-family: ui-monospace, monospace; }}
    .warn {{ background: #fff4ce; padding: 10px 12px; border-radius: 10px; }}
    .ok {{ background: #e8f5e9; padding: 10px 12px; border-radius: 10px; }}
    .noqr {{ margin: 16px 0; padding: 16px; background: #f1f3f5; border-radius: 12px; }}
    .qr {{ width: 220px; height: 220px; display: block; margin: 16px 0; border-radius: 12px; background: white; }}
    .qr-link {{ display: inline-block; }}
    .action-note {{ color: #4f5b66; font-weight: 600; }}
    code {{ word-break: break-all; }}
  </style>
  <script>
    async function copyText(value) {{
      try {{
        await navigator.clipboard.writeText(value);
        alert('Link copied');
      }} catch (e) {{
        alert('Copy failed. Please copy manually.');
      }}
    }}
  </script>
</head>
<body>
  <h1>Payment Requests: {html.escape(meta["bill_id"])}</h1>
  <p><strong>Recipient wallet:</strong> <code>{html.escape(meta["recipient_wallet"])}</code></p>
  <p>{html.escape(qr_note)}</p>
  <p>Share the QR image through structured media in chat runtimes. Avoid printing local file paths or raw Solana Pay links to end users.</p>
  {"".join(cards)}
</body>
</html>
"""


def main() -> None:
    args = build_parser().parse_args()
    payload = read_json(args.input_file)
    meta, requests = load_requests(payload)
    validations = {
        item.get("request_id", ""): validate_request(item) for item in requests
    }
    invalid_request_ids = [
        request_id for request_id, issues in validations.items() if issues
    ]
    if invalid_request_ids:
        payload = response(
            "error",
            f"Rejected {len(invalid_request_ids)} noncanonical payment requests",
            ["reject_invalid_requests", "regenerate_payment_requests"],
            [args.output_file] if args.output_file else [],
            {
                "bill_id": meta["bill_id"],
                "recipient_wallet": meta["recipient_wallet"],
                "validations": validations,
                "invalid_request_ids": invalid_request_ids,
            },
        )
        emit(payload, args.output_file)
        return

    output_dir = Path(args.output_dir) if args.output_dir else Path(".tmp_qr")
    if args.output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    qr_mode, qr_assets = generate_qr_assets(
        requests,
        output_dir,
        args.qr_dir_name,
        args.remote_qr_base,
        args.prefer_local_qr,
    )
    request_views, public_request_views, outbound_media, shareable_links = (
        build_request_views(
            requests, validations, qr_assets, output_dir, args.debug_view
        )
    )
    chat_share_text = build_chat_share_text(request_views, args.debug_view)

    artifacts = []
    if args.output_dir:
        html_path = output_dir / args.html_name
        markdown_path = output_dir / args.markdown_name
        html_path.write_text(
            to_html(meta, request_views, validations, qr_mode, args.debug_view),
            encoding="utf-8",
        )
        markdown_path.write_text(
            to_markdown(meta, request_views, validations, qr_mode, args.debug_view),
            encoding="utf-8",
        )
        artifacts = [str(html_path), str(markdown_path)]
        qr_artifacts = [
            media["source"]
            for media in outbound_media
            if media.get("source_type") == "path"
        ]
        artifacts.extend(qr_artifacts)

    if args.output_dir:
        summary = f"Rendered {len(requests)} payment requests into HTML and Markdown"
        next_actions = ["open_html_preview", "share_payment_links"]
    else:
        summary = f"Generated {len(requests)} payment request views (no files written)"
        next_actions = ["share_payment_links"]

    if qr_mode == "remote_url":
        next_actions.append("send_qr_image_url_or_rendered_page")
    elif qr_mode == "none":
        next_actions.append("install_qr_library_for_local_generation")

    payload = response(
        "success",
        summary,
        next_actions,
        artifacts + ([args.output_file] if args.output_file else []),
        {
            "bill_id": meta["bill_id"],
            "recipient_wallet": meta["recipient_wallet"],
            "warning_count": 0,
            "qr_mode": qr_mode,
            "rendered_files": {
                "html": str(output_dir / args.html_name) if args.output_dir else None,
                "markdown": str(output_dir / args.markdown_name)
                if args.output_dir
                else None,
            }
            if args.output_dir
            else None,
            "request_views": request_views,
            "public_request_views": public_request_views,
            "outbound_media": outbound_media,
            "shareable_links": shareable_links,
            "chat_share_text": chat_share_text,
            "validations": validations,
        },
    )
    emit(payload, args.output_file)


if __name__ == "__main__":
    main()
