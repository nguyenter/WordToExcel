from pathlib import Path
from io import BytesIO

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from app.services.word_to_excel_service import convert_docx_to_excel_bytes

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
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
    excel_bytes = convert_docx_to_excel_bytes(file_bytes)
    excel_name = f"{Path(filename).stem}.xlsx"

    return send_file(
        excel_bytes,
        as_attachment=True,
        download_name=excel_name,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
