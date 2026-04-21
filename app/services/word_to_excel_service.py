from io import BytesIO
from pathlib import Path
import re

import pandas as pd
from docx import Document


def extract_multiple_companies_from_docx(file_stream):
    doc = Document(file_stream)
    full_text = "\n".join([p.text.strip() for p in doc.paragraphs if p.text.strip()])
    blocks = re.split(r"(?=CÔNG TY)", full_text)
    all_data = []

    for block in blocks:
        block = block.strip()
        if not block.startswith("CÔNG TY"):
            continue

        lines = block.split("\n")
        company_name = lines[0].strip()
        clean_text = " ".join(lines)

        representative = ""
        phone = ""
        address = ""

        # Support "Đại diện:" and "Đại diện pháp luật:"
        rep_match = re.search(r"Đại diện(?: pháp luật)?:\s*([^Đ]+)", clean_text)
        if rep_match:
            representative = rep_match.group(1).strip()

        phone_match = re.search(r"Điện thoại:\s*([\d]+)", clean_text)
        if phone_match:
            phone = phone_match.group(1).strip()

        # Support "Địa chỉ:" and "Địa chỉ thuế:"
        addr_match = re.search(r"Địa chỉ(?: thuế)?:\s*(.+?)(?=Điện thoại:|Đại diện|$)", clean_text)
        if addr_match:
            address = addr_match.group(1).strip()

        all_data.append(
            {
                "Khách hàng": company_name,
                "Tên liên hệ": representative,
                "Điện thoại": phone,
                "Địa chỉ": address,
            }
        )

    return all_data


def convert_docx_to_excel_bytes(file_stream):
    if hasattr(file_stream, "seek"):
        file_stream.seek(0)

    rows = extract_multiple_companies_from_docx(file_stream)
    df = pd.DataFrame(rows)

    if not df.empty:
        df.insert(0, "STT", range(1, len(df) + 1))
    else:
        df = pd.DataFrame(columns=["STT", "Khách hàng", "Tên liên hệ", "Điện thoại", "Địa chỉ"])

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    output.seek(0)

    return output


def convert_docx_path_to_excel_path(docx_path, output_path=None):
    docx_path = Path(docx_path)
    if output_path is None:
        output_path = docx_path.with_suffix(".xlsx")
    else:
        output_path = Path(output_path)

    with docx_path.open("rb") as src:
        excel_bytes = convert_docx_to_excel_bytes(src)

    with output_path.open("wb") as dst:
        dst.write(excel_bytes.getvalue())

    return str(output_path)
