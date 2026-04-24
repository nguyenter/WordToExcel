from pathlib import Path
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from app.services.word_to_excel_service import convert_docx_to_excel_bytes

main_bp = Blueprint('main', __name__)
SAMPLE_WORD_PATH = Path(__file__).resolve().parents[2] / "data mẫu.pdf"
DOCX_REQUIRED_ENTRIES = (
    "[Content_Types].xml",
    "word/document.xml",
)
DOCX_BLOCKED_ENTRIES = (
    "word/vbaProject.bin",
    "word/vbaData.xml",
)


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
    if request.method == 'GET':
        return render_template('word_to_excel.html')

    upload = request.files.get('word_file')
    if upload is None or upload.filename == '':
        flash('Vui lòng chọn file Word để tải lên.', 'danger')
        return redirect(url_for('main.word_to_excel'))

    filename = secure_filename(upload.filename)
    suffix = Path(filename).suffix.lower()
    if suffix != '.docx':
        flash('Chỉ hỗ trợ file .docx.', 'danger')
        return redirect(url_for('main.word_to_excel'))

    file_bytes = BytesIO(upload.read())
    validation_error = _validate_docx_content(file_bytes)
    if validation_error:
        flash(validation_error, 'danger')
        return redirect(url_for('main.word_to_excel'))

    excel_bytes = convert_docx_to_excel_bytes(file_bytes)
    excel_name = f"{Path(filename).stem}.xlsx"

    return send_file(
        excel_bytes,
        as_attachment=True,
        download_name=excel_name,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


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
