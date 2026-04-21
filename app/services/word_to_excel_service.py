from io import BytesIO

import pandas as pd
from docx import Document


def extract_multiple_companies_from_docx(file_stream):
    doc = Document(file_stream)

    all_data = []
    current = None

    for para in doc.paragraphs:
        text = para.text.strip()

        if not text:
            continue

        if text.startswith("CÔNG TY"):
            if current:
                all_data.append(current)

            current = {
                "Khách hàng": text,
                "Tên liên hệ": "",
                "Điện thoại": "",
                "Địa chỉ": "",
            }
        elif current:
            if "Đại diện:" in text:
                current["Tên liên hệ"] = text.replace("Đại diện:", "").strip()
            elif "Điện thoại:" in text:
                current["Điện thoại"] = text.replace("Điện thoại:", "").strip()
            elif "Địa chỉ:" in text:
                current["Địa chỉ"] = text.replace("Địa chỉ:", "").strip()

    if current:
        all_data.append(current)

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
