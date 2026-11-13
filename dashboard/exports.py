import csv
import io
import os
from pathlib import Path
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle


HEADERS = ["Mã nhân viên", "Họ và tên", "Phòng ban", "Ngày", "Status", "Clock In", "Clock Out", "Ghi chú"]
FIELDS = ["employee_code", "name", "department", "work_date", "status", "clock_in", "clock_out", "note"]
STATUS_LABELS = {
    "Online": "Online",
    "AL": "AL - Nghỉ phép năm",
    "UL": "UL - Nghỉ không lương",
    "UAL": "UAL - Nghỉ không phép",
    "SL": "SL - Nghỉ ốm",
}


def export_rows(rows, file_format):
    if file_format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(HEADERS)
        for row in rows:
            writer.writerow([row.get(field) or "" for field in FIELDS])
        return output.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", "csv"
    if file_format == "xlsx":
        return _build_xlsx(rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    if file_format == "pdf":
        return _build_pdf(rows), "application/pdf", "pdf"
    raise ValueError("Unsupported attendance export format")


def _build_xlsx(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Attendance"
    sheet.append(HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="173A35")
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        sheet.append([row.get(field) or "" for field in FIELDS])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in zip("ABCDEFGH", (18, 26, 22, 14, 14, 14, 14, 44)):
        sheet.column_dimensions[column].width = width
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _pdf_font():
    windows_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidates = (
        windows_dir / "arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    )
    for font_path in candidates:
        if font_path.exists():
            pdfmetrics.registerFont(TTFont("QualitySans", str(font_path)))
            return "QualitySans"
    return "Helvetica"


def _build_pdf(rows):
    font_name = _pdf_font()
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Attendance report",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AttendanceTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=15,
        leading=19,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#173a35"),
        spaceAfter=12,
    )
    cell_style = ParagraphStyle(
        "AttendanceCell",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=7,
        leading=9,
    )
    table_data = [[Paragraph(escape(header), cell_style) for header in HEADERS]]
    for row in rows:
        values = [row.get(field) or "" for field in FIELDS]
        values[4] = STATUS_LABELS.get(values[4], values[4])
        table_data.append([Paragraph(escape(str(value)), cell_style) for value in values])
    table = Table(
        table_data,
        repeatRows=1,
        colWidths=[27 * mm, 34 * mm, 29 * mm, 23 * mm, 35 * mm, 22 * mm, 22 * mm, 75 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173a35")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dce4dc")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5ef")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    document.build([Paragraph("BÁO CÁO CHẤM CÔNG", title_style), table])
    return output.getvalue()
