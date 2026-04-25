import os
import secrets
import tempfile
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from app.services.word_to_excel_service import convert_docx_to_excel_bytes

main_bp = Blueprint('main', __name__)
SAMPLE_WORD_PATH = Path(__file__).resolve().parents[2] / "data mẫu.pdf"
FIXED_PRICE = 5000
DOCX_REQUIRED_ENTRIES = (
    "[Content_Types].xml",
    "word/document.xml",
)
DOCX_BLOCKED_ENTRIES = (
    "word/vbaProject.bin",
    "word/vbaData.xml",
)


def _get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None, "Thiếu cấu hình SUPABASE_URL hoặc SUPABASE_KEY."

    try:
        from supabase import create_client
    except ImportError:
        return None, "Thiếu thư viện supabase. Hãy cài dependencies mới."

    return create_client(url, key), None


def _get_payos():
    client_id = os.getenv("PAYOS_CLIENT_ID")
    api_key = os.getenv("PAYOS_API_KEY")
    checksum_key = os.getenv("PAYOS_CHECKSUM_KEY")
    if not client_id or not api_key or not checksum_key:
        return None, "Thiếu cấu hình PayOS trong biến môi trường."

    try:
        from payos import PayOS
    except ImportError:
        return None, "Thiếu thư viện payos. Hãy cài dependencies mới."

    return PayOS(client_id=client_id, api_key=api_key, checksum_key=checksum_key), None


def _utc_now():
    return datetime.now(timezone.utc)


def _utc_now_iso():
    return _utc_now().isoformat()


def _to_utc_iso(dt_obj: datetime):
    return dt_obj.astimezone(timezone.utc).isoformat()


def _pluck(data, key, default=None):
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(data, key, default)


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _generate_order_code():
    # Millisecond-ish + random tail to reduce collision risk.
    return int(f"{int(time.time() * 1000)}{secrets.randbelow(90) + 10}")


def _safe_cleanup_file(file_path: str):
    if not file_path:
        return
    try:
        path = Path(file_path)
        if path.exists() and path.is_file():
            path.unlink()
    except Exception:
        pass


def _cleanup_expired_orders():
    supabase, error = _get_supabase()
    if error:
        return

    try:
        now_iso = _utc_now_iso()
        res = (
            supabase.table("orders")
            .select("order_code,file_path,status,expires_at")
            .in_("status", ["PENDING", "PAID"])
            .lt("expires_at", now_iso)
            .execute()
        )
        for item in res.data or []:
            _safe_cleanup_file(item.get("file_path"))
            (
                supabase.table("orders")
                .update({"status": "EXPIRED"})
                .eq("order_code", item.get("order_code"))
                .execute()
            )
    except Exception:
        # Cleanup is best-effort only.
        pass


def _mark_order_paid(supabase, order_code):
    order_code_int = _to_int(order_code)
    if order_code_int is None:
        return False

    order_res = (
        supabase.table("orders")
        .select("status")
        .eq("order_code", order_code_int)
        .limit(1)
        .execute()
    )
    order = (order_res.data or [None])[0]
    if not order:
        return False
    if order.get("status") in {"DOWNLOADED", "EXPIRED"}:
        return False

    (
        supabase.table("orders")
        .update({"status": "PAID", "paid_at": _utc_now_iso()})
        .eq("order_code", order_code_int)
        .execute()
    )
    return True


def _sync_paid_status_from_payos(payos, supabase, order_code):
    """
    Best-effort fallback when webhook is delayed/missed:
    query PayOS directly and mark order as PAID if confirmed.
    """
    order_code_int = _to_int(order_code)
    if order_code_int is None:
        return False

    candidates = []
    if hasattr(payos, "getPaymentLinkInformation"):
        candidates.append(lambda: payos.getPaymentLinkInformation(order_code_int))
    if hasattr(payos, "getPaymentLinkInfomation"):
        candidates.append(lambda: payos.getPaymentLinkInfomation(order_code_int))
    if hasattr(payos, "payment_requests") and hasattr(payos.payment_requests, "get"):
        candidates.append(lambda: payos.payment_requests.get(order_code_int))

    for call in candidates:
        try:
            info = call()
        except Exception:
            continue

        data = _pluck(info, "data", info)
        status = (_pluck(data, "status", "") or "").upper()
        amount = _to_int(_pluck(data, "amount"))
        if status == "PAID" and amount == FIXED_PRICE:
            return _mark_order_paid(supabase, order_code_int)

    return False


def _validate_docx_content(file_bytes: BytesIO) -> str | None:
    """Return an error message if the upload is unsafe/invalid."""
    if hasattr(file_bytes, "seek"):
        file_bytes.seek(0)
    magic = file_bytes.read(4)
    if magic != b"PK\x03\x04":
        return "File tải lên không phải .docx hợp lệ (định dạng nén Office)."

    if hasattr(file_bytes, "seek"):
        file_bytes.seek(0)

    try:
        with ZipFile(file_bytes) as archive:
            names = archive.namelist()
            names_set = set(names)
            for required_entry in DOCX_REQUIRED_ENTRIES:
                if required_entry not in names_set:
                    return "File .docx không hợp lệ hoặc bị thiếu cấu trúc bắt buộc."

            lower_names = [name.lower() for name in names]
            for blocked_entry in DOCX_BLOCKED_ENTRIES:
                blocked_entry = blocked_entry.lower()
                if any(
                    name == blocked_entry or name.startswith(blocked_entry)
                    for name in lower_names
                ):
                    return "File chứa thành phần macro/payload không được phép."

            try:
                content_types_xml = archive.read("[Content_Types].xml").decode(
                    "utf-8",
                    errors="ignore",
                ).lower()
            except KeyError:
                return "File .docx không hợp lệ hoặc bị thiếu cấu trúc bắt buộc."

            if "macroenabled" in content_types_xml:
                return "File chứa thành phần macro/payload không được phép."

            # Basic anti-zip-bomb guard.
            total_uncompressed = sum(info.file_size for info in archive.infolist())
            if total_uncompressed > 50 * 1024 * 1024:
                return "Nội dung file giải nén quá lớn, upload bị từ chối."
    except BadZipFile:
        return "File tải lên không phải .docx hợp lệ."
    finally:
        if hasattr(file_bytes, "seek"):
            file_bytes.seek(0)

    return None

@main_bp.route('/')
def index():
    return redirect(url_for('main.word_to_excel'))


@main_bp.route('/ping', methods=['GET'])
def ping():
    # Lightweight endpoint for uptime monitors (Render/UptimeRobot).
    return jsonify({"status": "ok", "service": "word-to-excel"}), 200


@main_bp.app_errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_error):
    flash('File quá lớn. Vui lòng tải file nhỏ hơn giới hạn cho phép.', 'danger')
    return redirect(url_for('main.word_to_excel'))


@main_bp.route('/word-to-excel', methods=['GET', 'POST'])
def word_to_excel():
    _cleanup_expired_orders()

    if request.method == 'GET':
        return render_template('word_to_excel.html')

    # Hard-block legacy direct download flow: all downloads must go through payment APIs.
    flash('Hệ thống yêu cầu thanh toán trước khi tải file. Vui lòng bật JavaScript và thao tác lại.', 'warning')
    return redirect(url_for('main.word_to_excel'))


@main_bp.route('/sample-word')
def sample_word():
    if not SAMPLE_WORD_PATH.exists():
        flash('Không tìm thấy file mẫu Word (PDF).', 'danger')
        return redirect(url_for('main.word_to_excel'))

    return send_file(
        SAMPLE_WORD_PATH,
        as_attachment=False,
        download_name='data-mau.pdf',
        mimetype='application/pdf',
    )


@main_bp.route('/api/upload-convert', methods=['POST'])
def upload_convert():
    _cleanup_expired_orders()

    supabase, supabase_error = _get_supabase()
    if supabase_error:
        return jsonify({"ok": False, "message": supabase_error}), 500

    upload = request.files.get('word_file')
    if upload is None or upload.filename == '':
        return jsonify({"ok": False, "message": "Vui lòng chọn file Word để tải lên."}), 400

    filename = secure_filename(upload.filename)
    suffix = Path(filename).suffix.lower()
    if suffix != '.docx':
        return jsonify({"ok": False, "message": "Chỉ hỗ trợ file .docx."}), 400

    file_bytes = BytesIO(upload.read())
    validation_error = _validate_docx_content(file_bytes)
    if validation_error:
        return jsonify({"ok": False, "message": validation_error}), 400

    excel_bytes = convert_docx_to_excel_bytes(file_bytes)

    order_code = _generate_order_code()
    temp_dir = Path(tempfile.gettempdir())
    excel_path = temp_dir / f"{order_code}.xlsx"
    with excel_path.open("wb") as out:
        out.write(excel_bytes.getvalue())

    expires_at = _utc_now() + timedelta(minutes=current_app.config.get("FILE_TTL_MINUTES", 15))
    insert_payload = {
        "order_code": order_code,
        "status": "PENDING",
        "amount": FIXED_PRICE,
        "file_path": str(excel_path),
        "created_at": _utc_now_iso(),
        "expires_at": _to_utc_iso(expires_at),
    }
    try:
        supabase.table("orders").insert(insert_payload).execute()
    except Exception as exc:
        _safe_cleanup_file(str(excel_path))
        return jsonify({"ok": False, "message": f"Không thể tạo đơn hàng: {exc}"}), 500

    return jsonify({
        "ok": True,
        "orderCode": order_code,
        "amount": FIXED_PRICE,
        "expiresAt": _to_utc_iso(expires_at),
    })


@main_bp.route('/api/create-payment/<int:order_code>', methods=['POST'])
def create_payment(order_code):
    _cleanup_expired_orders()

    supabase, supabase_error = _get_supabase()
    if supabase_error:
        return jsonify({"ok": False, "message": supabase_error}), 500

    payos, payos_error = _get_payos()
    if payos_error:
        return jsonify({"ok": False, "message": payos_error}), 500

    order_res = (
        supabase.table("orders")
        .select("*")
        .eq("order_code", order_code)
        .limit(1)
        .execute()
    )
    order = (order_res.data or [None])[0]
    if not order:
        return jsonify({"ok": False, "message": "Không tìm thấy đơn hàng."}), 404

    if order.get("status") == "PAID":
        return jsonify({"ok": True, "alreadyPaid": True, "orderCode": order_code})

    if order.get("status") in {"DOWNLOADED", "EXPIRED"}:
        return jsonify({"ok": False, "message": "Đơn hàng đã hết hiệu lực."}), 410

    public_base_url = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/")
    return_url = f"{public_base_url}/word-to-excel" if public_base_url else request.host_url.rstrip("/") + "/word-to-excel"
    cancel_url = return_url
    payment_data = {
        "orderCode": order_code,
        "amount": FIXED_PRICE,
        "description": "Word to Excel",
        "returnUrl": return_url,
        "cancelUrl": cancel_url,
        "items": [
            {
                "name": "Word to Excel",
                "quantity": 1,
                "price": FIXED_PRICE,
            }
        ],
    }

    try:
        # Compatible with multiple PayOS Python SDK versions.
        pay_res = None
        last_error = None

        # Variant A: old SDK style.
        try:
            pay_res = payos.createPaymentLink(payment_data)
        except Exception as exc:
            last_error = exc

        # Variant B: newer SDK style payos.payment_requests.create(dict).
        if pay_res is None:
            try:
                pay_res = payos.payment_requests.create(payment_data)
            except Exception as exc:
                last_error = exc

        # Variant C: newer SDK with typed request object.
        if pay_res is None:
            try:
                from payos.types import CreatePaymentLinkRequest

                request_obj = CreatePaymentLinkRequest(
                    orderCode=payment_data["orderCode"],
                    amount=payment_data["amount"],
                    description=payment_data["description"],
                    returnUrl=payment_data["returnUrl"],
                    cancelUrl=payment_data["cancelUrl"],
                    items=payment_data["items"],
                )
                try:
                    pay_res = payos.payment_requests.create(request_obj)
                except Exception:
                    pay_res = payos.createPaymentLink(request_obj)
            except Exception as exc:
                last_error = exc

        if pay_res is None:
            raise RuntimeError(str(last_error) if last_error else "Không thể tạo link thanh toán với SDK PayOS hiện tại.")
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Lỗi tạo thanh toán: {exc}"}), 502

    if isinstance(pay_res, dict):
        checkout_url = pay_res.get("checkoutUrl") or pay_res.get("checkout_url")
        qr_code = pay_res.get("qrCode") or pay_res.get("qr_code")
    else:
        checkout_url = getattr(pay_res, "checkoutUrl", None) or getattr(pay_res, "checkout_url", None)
        qr_code = getattr(pay_res, "qrCode", None) or getattr(pay_res, "qr_code", None)
        if not checkout_url and hasattr(pay_res, "to_json"):
            try:
                payload_json = pay_res.to_json()
                checkout_url = payload_json.get("checkoutUrl") or payload_json.get("checkout_url")
                qr_code = payload_json.get("qrCode") or payload_json.get("qr_code")
            except Exception:
                pass

    return jsonify({
        "ok": True,
        "orderCode": order_code,
        "checkoutUrl": checkout_url,
        "qrCode": qr_code,
    })


@main_bp.route('/api/webhook/payos', methods=['POST'])
def payos_webhook():
    _cleanup_expired_orders()

    supabase, supabase_error = _get_supabase()
    if supabase_error:
        return jsonify({"ok": False, "message": supabase_error}), 500

    payos, payos_error = _get_payos()
    if payos_error:
        return jsonify({"ok": False, "message": payos_error}), 500

    payload = request.get_json(silent=True) or {}
    try:
        verified = payos.verifyPaymentWebhookData(payload)
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Webhook không hợp lệ: {exc}"}), 400

    data = _pluck(verified, "data", verified)
    status = (_pluck(data, "status", "") or "").upper()
    amount = _to_int(_pluck(data, "amount"))
    order_code = _to_int(_pluck(data, "orderCode"))

    if status == "PAID" and amount == FIXED_PRICE and order_code is not None:
        _mark_order_paid(supabase, order_code)

    return jsonify({"ok": True})


@main_bp.route('/api/check-payment/<int:order_code>', methods=['GET'])
def check_payment(order_code):
    _cleanup_expired_orders()

    supabase, supabase_error = _get_supabase()
    if supabase_error:
        return jsonify({"ok": False, "message": supabase_error}), 500

    res = (
        supabase.table("orders")
        .select("status,expires_at")
        .eq("order_code", order_code)
        .limit(1)
        .execute()
    )
    order = (res.data or [None])[0]
    if not order:
        return jsonify({"ok": False, "message": "Không tìm thấy đơn hàng."}), 404

    # Fallback sync: if webhook missed/delayed, query PayOS directly.
    if order.get("status") == "PENDING":
        payos, payos_error = _get_payos()
        if not payos_error:
            if _sync_paid_status_from_payos(payos, supabase, order_code):
                refreshed = (
                    supabase.table("orders")
                    .select("status,expires_at")
                    .eq("order_code", order_code)
                    .limit(1)
                    .execute()
                )
                order = (refreshed.data or [order])[0]

    return jsonify({
        "ok": True,
        "paid": order.get("status") == "PAID",
        "status": order.get("status"),
        "expiresAt": order.get("expires_at"),
    })


@main_bp.route('/api/download-token/<int:order_code>', methods=['POST'])
def create_download_token(order_code):
    _cleanup_expired_orders()

    supabase, supabase_error = _get_supabase()
    if supabase_error:
        return jsonify({"ok": False, "message": supabase_error}), 500

    res = (
        supabase.table("orders")
        .select("*")
        .eq("order_code", order_code)
        .limit(1)
        .execute()
    )
    order = (res.data or [None])[0]
    if not order:
        return jsonify({"ok": False, "message": "Không tìm thấy đơn hàng."}), 404
    if order.get("status") != "PAID":
        return jsonify({"ok": False, "message": "Đơn hàng chưa thanh toán."}), 403

    token = secrets.token_urlsafe(32)
    token_expires_at = _utc_now() + timedelta(minutes=current_app.config.get("DOWNLOAD_TOKEN_TTL_MINUTES", 3))
    (
        supabase.table("orders")
        .update({
            "download_token": token,
            "token_expires_at": _to_utc_iso(token_expires_at),
        })
        .eq("order_code", order_code)
        .execute()
    )
    return jsonify({
        "ok": True,
        "downloadUrl": url_for("main.download_by_token", token=token),
        "tokenExpiresAt": _to_utc_iso(token_expires_at),
    })


@main_bp.route('/download/<token>', methods=['GET'])
def download_by_token(token):
    _cleanup_expired_orders()

    supabase, supabase_error = _get_supabase()
    if supabase_error:
        return "Thiếu cấu hình Supabase.", 500

    res = (
        supabase.table("orders")
        .select("*")
        .eq("download_token", token)
        .limit(1)
        .execute()
    )
    order = (res.data or [None])[0]
    if not order:
        return "Liên kết tải không hợp lệ.", 404

    token_expires_at = order.get("token_expires_at")
    if not token_expires_at:
        return "Liên kết tải đã hết hạn.", 410

    now_iso = _utc_now_iso()
    if token_expires_at < now_iso:
        return "Liên kết tải đã hết hạn.", 410

    if order.get("status") != "PAID":
        return "Đơn hàng chưa hợp lệ để tải.", 403

    file_path = order.get("file_path")
    if not file_path or not Path(file_path).exists():
        return "File không còn tồn tại.", 410

    excel_name = f"{order.get('order_code')}.xlsx"
    response = send_file(
        file_path,
        as_attachment=True,
        download_name=excel_name,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )

    _safe_cleanup_file(file_path)
    (
        supabase.table("orders")
        .update({
            "status": "DOWNLOADED",
            "download_token": None,
            "token_expires_at": None,
        })
        .eq("order_code", order.get("order_code"))
        .execute()
    )
    return response
