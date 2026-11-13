from io import BytesIO
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException


EMPLOYEE_HEADERS = ("employee_code", "name", "department", "position")
REQUIRED_HEADERS = ("employee_code", "name")
MAX_IMPORT_ROWS = 500


class EmployeeWorkbookError(ValueError):
    pass


def employee_template_bytes():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Employees"
    sheet.append(EMPLOYEE_HEADERS)
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="055B65")
        cell.font = Font(bold=True, color="FBFCFC")
        cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = "A1:D1"
    for column, width in {"A": 22, "B": 30, "C": 26, "D": 26}.items():
        sheet.column_dimensions[column].width = width

    guide = workbook.create_sheet("Guide")
    guide.append(("Cột", "Bắt buộc", "Mô tả"))
    guide.append(("employee_code", "Có", "Mã nhân viên duy nhất; giữ nguyên định dạng mã."))
    guide.append(("name", "Có", "Họ và tên nhân viên."))
    guide.append(("department", "Không", "Phòng ban."))
    guide.append(("position", "Không", "Chức vụ."))
    for cell in guide[1]:
        cell.fill = PatternFill("solid", fgColor="055B65")
        cell.font = Font(bold=True, color="FBFCFC")
    guide.column_dimensions["A"].width = 22
    guide.column_dimensions["B"].width = 14
    guide.column_dimensions["C"].width = 62

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_employee_workbook(uploaded_file):
    try:
        workbook = load_workbook(uploaded_file, read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile, OSError, ValueError) as error:
        raise EmployeeWorkbookError("Không đọc được file Excel. Hãy dùng file .xlsx theo mẫu.") from error

    try:
        sheet = workbook.active
        if sheet.max_row > MAX_IMPORT_ROWS + 1:
            raise EmployeeWorkbookError(f"File vượt quá giới hạn {MAX_IMPORT_ROWS} dòng dữ liệu.")
        raw_headers = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
        headers = [_cell_text(value).lower() for value in raw_headers]
        if len(headers) != len(set(headers)):
            raise EmployeeWorkbookError("Tên cột trong file bị trùng.")
        missing_headers = [header for header in REQUIRED_HEADERS if header not in headers]
        if missing_headers:
            raise EmployeeWorkbookError(
                "Thiếu cột bắt buộc: " + ", ".join(missing_headers)
            )

        column_indexes = {header: index for index, header in enumerate(headers) if header}
        employees = []
        errors = []
        seen_codes = set()
        for row_number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            record = {
                header: _cell_text(values[index] if index < len(values) else None)
                for header, index in column_indexes.items()
                if header in EMPLOYEE_HEADERS
            }
            if not any(record.values()):
                continue
            if len(employees) + len(errors) >= MAX_IMPORT_ROWS:
                errors.append(f"Dòng {row_number}: vượt quá giới hạn {MAX_IMPORT_ROWS} dòng dữ liệu.")
                break

            employee_code = record.get("employee_code", "")
            name = record.get("name", "")
            if not employee_code:
                errors.append(f"Dòng {row_number}: thiếu employee_code.")
                continue
            if not name:
                errors.append(f"Dòng {row_number}: thiếu name.")
                continue
            if len(employee_code) > 50:
                errors.append(f"Dòng {row_number}: employee_code vượt quá 50 ký tự.")
                continue
            if len(name) > 100:
                errors.append(f"Dòng {row_number}: name vượt quá 100 ký tự.")
                continue
            if len(record.get("department", "")) > 100:
                errors.append(f"Dòng {row_number}: department vượt quá 100 ký tự.")
                continue
            if len(record.get("position", "")) > 100:
                errors.append(f"Dòng {row_number}: position vượt quá 100 ký tự.")
                continue
            if employee_code in seen_codes:
                errors.append(f"Dòng {row_number}: employee_code '{employee_code}' bị lặp trong file.")
                continue
            seen_codes.add(employee_code)
            employees.append({
                "row_number": row_number,
                "employee_code": employee_code,
                "name": name,
                "department": record.get("department", ""),
                "position": record.get("position", ""),
            })
        return employees, errors
    finally:
        workbook.close()
