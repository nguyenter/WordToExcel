from io import BytesIO
from pathlib import Path
import re

import pandas as pd
from docx import Document


def _normalize_phone_number(raw: str) -> str:
    digits = re.sub(r"\D+", "", raw or "")
    if digits.startswith("02"):
        return ""
    return digits


def _extract_hotline_numbers(text: str) -> str:
    """
    Extract hotline numbers from a line like:
    "Hotline: 0913 615 785, 098 383 7474"
    Apply constraint: if number starts with 02x... => drop it.
    """
    if not text:
        return ""

    # Keep sequences that look like Vietnamese phone numbers starting with 0
    candidates = re.findall(r"(?:\b0[\d\s\.\-]{8,}\b)", text)
    normalized = []
    for c in candidates:
        n = _normalize_phone_number(c)
        if n:
            normalized.append(n)

    # de-dup while preserving order
    seen = set()
    result = []
    for n in normalized:
        if n not in seen:
            seen.add(n)
            result.append(n)

    return ", ".join(result)


def _extract_value_after_label(lines: list[str], label_regex: str) -> str:
    """
    Find first line matching label_regex and return the text after the label.
    Supports separators like ":" or tab or spaces.
    """
    if not lines:
        return ""

    label_re = re.compile(label_regex, flags=re.IGNORECASE)
    for line in lines:
        if not line:
            continue
        m = label_re.match(line.strip())
        if not m:
            continue
        # Remaining text after the label (and separators) is captured in group(1)
        value = (m.group(1) or "").strip()
        return value
    return ""


def _looks_like_address_line(line: str) -> bool:
    if not line:
        return False

    s = line.strip()
    if not s:
        return False

    # Common Vietnamese address tokens (also include ascii variants)
    tokens = (
        r"\b(đường|duong|phố|pho|số|so|ngõ|ngo|hẻm|hem|hẻm|hxh|"
        r"phường|phuong|p\.|quận|quan|q\.|huyện|huyen|xã|xa|"
        r"tỉnh|tinh|thành\s*phố|thanh\s*pho|tp\.|t\.p\.|"
        r"tòa|toa|tầng|tang|lầu|lau|khu|ấp|ap|thôn|thon|xóm|xom)\b"
    )
    if re.search(tokens, s, flags=re.IGNORECASE):
        return True

    # Heuristic: if it contains numbers + commas (often full address)
    if re.search(r"\d", s) and ("," in s or "-" in s):
        return True

    return False


def _parse_company_block_lines(lines: list[str]) -> dict | None:
    lines = [l.strip() for l in lines if l.strip()]
    if not lines:
        return None

    first_line = lines[0]
    joined = " ".join(lines)

    # Old format: starts with "CÔNG TY ..."
    if first_line.upper().startswith("CÔNG TY"):
        company_name = first_line
        # Accept both old "label:" style and the new tab/space-separated style:
        # "Địa chỉ\tSố 43/9 ...", "Điện thoại 0918...", "Người đại diện\tNgô ..."
        representative = _extract_value_after_label(
            lines,
            r"^người\s+đại\s+diện\s*[:\t ]+\s*(.+)$",
        )
        if not representative:
            representative = _extract_value_after_label(
                lines,
                r"^đại\s+diện(?:\s+pháp\s+luật)?\s*[:\t ]+\s*(.+)$",
            )

        address = _extract_value_after_label(
            lines,
            r"^địa\s+chỉ(?:\s+thuế)?\s*[:\t ]+\s*(.+)$",
        )

        phone_raw = _extract_value_after_label(
            lines,
            r"^điện\s+thoại\s*[:\t ]+\s*(.+)$",
        )
        if phone_raw:
            phone = _extract_hotline_numbers(phone_raw) or _normalize_phone_number(phone_raw)
        else:
            phone = ""
        # Force Excel to treat plain digit phone numbers as text
        # to preserve leading zero (e.g. 0918...).
        if phone and re.fullmatch(r"\d+", phone) and phone.startswith("0"):
            phone = "'" + phone

        return {
            "Khách hàng": company_name,
            "Tên liên hệ": representative,
            "Điện thoại": phone,
            "Địa chỉ": address,
        }

    # New format example:
    # 1) Company line (often contains " - ")
    # 2) "Ngày cập nhật gần nhất: ..."
    # 3) Address line(s)
    # 4) "Hotline: ..."
    # 5) email line
    company_name = first_line

    hotline_line = next((l for l in lines if re.search(r"\bhotline\b", l, flags=re.IGNORECASE)), "")
    phone = _extract_hotline_numbers(hotline_line)

    # Address: collect lines after the first line, excluding "Ngày cập nhật...", hotline, and email-only lines
    address_parts: list[str] = []
    for l in lines[1:]:
        if re.match(r"^(Ngày\s+cập\s+nhật|Ngay\s+cap\s+nhat)", l, flags=re.IGNORECASE):
            continue
        if re.search(r"\bhotline\b", l, flags=re.IGNORECASE):
            continue
        if _looks_like_address_line(l):
            address_parts.append(l)

    address = " ".join(address_parts).strip()

    return {
        "Khách hàng": company_name,
        "Tên liên hệ": "",
        "Điện thoại": phone,
        "Địa chỉ": address,
    }


def extract_multiple_companies_from_docx(file_stream):
    doc = Document(file_stream)

    # Keep blank lines so we can split by paragraph gaps
    raw_lines = [p.text.rstrip() for p in doc.paragraphs]
    text = "\n".join(raw_lines).strip()
    if not text:
        return []

    # Split blocks by empty-line gaps (or many newlines)
    blocks = re.split(r"\n\s*\n+", text)
    all_data: list[dict] = []

    # Backward-compat: some files might have no blank lines; fallback split by "CÔNG TY"
    if len(blocks) == 1 and "CÔNG TY" in text.upper():
        blocks = re.split(r"(?=CÔNG TY)", text, flags=re.IGNORECASE)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        parsed = _parse_company_block_lines(block.split("\n"))
        if parsed:
            all_data.append(parsed)

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
