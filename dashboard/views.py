from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .api_client import APIError, api_request
from .employee_imports import EmployeeWorkbookError, employee_template_bytes, parse_employee_workbook
from .exports import export_rows
from .permissions import ALL_ROLES, ROLE_LABELS, WRITE_ROLES, role_required


ATTENDANCE_STATUS_LABELS = {
    "Online": "Online - Có mặt",
    "AL": "AL - Nghỉ phép năm",
    "UL": "UL - Nghỉ không lương",
    "UAL": "UAL - Nghỉ không phép",
    "SL": "SL - Nghỉ ốm",
}
LEAVE_STATUS_LABELS = {code: label for code, label in ATTENDANCE_STATUS_LABELS.items() if code != "Online"}


def show_api_error(request, error):
    messages.error(request, str(error))


@role_required(*ALL_ROLES)
def dashboard(request):
    today_date = timezone.localdate()
    today = today_date.isoformat()
    data = {
        "today": today,
        "active_employees": 0,
        "attendance": {},
        "open_handovers": 0,
        "recent_handovers": [],
    }
    try:
        data.update(api_request("api/dashboard"))
    except APIError as error:
        show_api_error(request, error)
    attendance_counts = data.get("attendance", {})
    data["present_today"] = attendance_counts.get("Online", 0)
    data["leave_today"] = sum(attendance_counts.get(code, 0) for code in ("AL", "UL", "UAL", "SL"))
    data["attendance_total"] = sum(attendance_counts.values())
    data["unrecorded_today"] = max(0, data["active_employees"] - data["attendance_total"])
    data["attendance_rate"] = round(data["present_today"] * 100 / data["active_employees"]) if data["active_employees"] else 0

    first_day = today_date - timedelta(days=6)
    try:
        report_rows = api_request(
            "api/attendance/report",
            query={"start_date": first_day.isoformat(), "end_date": today},
        )
    except APIError as error:
        show_api_error(request, error)
        report_rows = []

    daily_counts = {}
    for row in report_rows:
        day_counts = daily_counts.setdefault(row["work_date"], {"present": 0, "leave": 0})
        if row["status"] == "Online":
            day_counts["present"] += 1
        else:
            day_counts["leave"] += 1
    max_daily_count = max(
        (counts["present"] + counts["leave"] for counts in daily_counts.values()),
        default=1,
    ) or 1
    data["chart_scale"] = max_daily_count
    data["chart_midpoint"] = max(1, round(max_daily_count / 2))
    weekday_labels = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")
    chart_days = []
    for offset in range(7):
        day = first_day + timedelta(days=offset)
        counts = daily_counts.get(day.isoformat(), {"present": 0, "leave": 0})
        chart_days.append({
            "label": day.strftime("%d/%m"),
            "weekday": weekday_labels[day.weekday()],
            "present": counts["present"],
            "leave": counts["leave"],
            "present_height": round(counts["present"] * 100 / max_daily_count),
            "leave_height": round(counts["leave"] * 100 / max_daily_count),
        })
    data["chart_days"] = chart_days
    data["weekly_present"] = sum(day["present"] for day in chart_days)
    data["weekly_leave"] = sum(day["leave"] for day in chart_days)

    try:
        data["recent_attendance"] = api_request("api/attendance", query={"work_date": today})[:5]
    except APIError as error:
        show_api_error(request, error)
        data["recent_attendance"] = []
    return render(request, "dashboard/index.html", data)


@role_required("admin", "staff", "viewer", write_roles=WRITE_ROLES)
def employees(request):
    if request.method == "GET" and request.GET.get("download_template") == "1":
        response = HttpResponse(
            employee_template_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="employee_import_template.xlsx"'
        return response

    if request.method == "POST":
        employee_file = request.FILES.get("employee_file")
        if employee_file:
            if employee_file.size > 5 * 1024 * 1024:
                messages.error(request, "File vượt quá giới hạn 5 MB.")
                return redirect("employees")
            if not employee_file.name.lower().endswith(".xlsx"):
                messages.error(request, "Chỉ hỗ trợ file Excel .xlsx.")
                return redirect("employees")
            try:
                employee_rows, row_errors = parse_employee_workbook(employee_file)
            except EmployeeWorkbookError as error:
                messages.error(request, str(error))
                return redirect("employees")

            created_count = 0
            for row in employee_rows:
                payload = {
                    key: row[key]
                    for key in ("employee_code", "name", "department", "position")
                }
                try:
                    api_request("api/employees", method="POST", payload=payload)
                    created_count += 1
                except APIError as error:
                    row_errors.append(f"Dòng {row['row_number']}: {error}")

            if created_count:
                messages.success(request, f"Đã thêm {created_count} nhân viên từ file Excel.")
            if not employee_rows and not row_errors:
                row_errors.append("File không có dòng dữ liệu nhân viên.")
            for error in row_errors[:12]:
                messages.error(request, error)
            if len(row_errors) > 12:
                messages.error(request, f"Còn {len(row_errors) - 12} lỗi khác; hãy sửa file và nhập lại.")
            return redirect("employees")

        payload = {
            "employee_code": request.POST.get("employee_code", "").strip(),
            "name": request.POST.get("name", "").strip(),
            "department": request.POST.get("department", "").strip(),
            "position": request.POST.get("position", "").strip(),
        }
        try:
            api_request("api/employees", method="POST", payload=payload)
            messages.success(request, "Đã thêm nhân viên.")
            return redirect("employees")
        except APIError as error:
            show_api_error(request, error)
    query = request.GET.get("q", "").strip()
    try:
        employee_rows = api_request("api/employees", query={"q": query})
    except APIError as error:
        show_api_error(request, error)
        employee_rows = []
    return render(request, "dashboard/employees.html", {"employees": employee_rows, "query": query})


@role_required("admin", "staff", "viewer", write_roles=WRITE_ROLES)
def attendance(request):
    selected_date = timezone.localdate().isoformat()
    if request.method == "POST":
        employee_code = request.POST.get("employee_code", "").strip()
        try:
            scan_result = api_request(
                "api/attendance/scan",
                method="POST",
                payload={"employee_code": employee_code},
            )
            request.session["last_attendance_scan"] = scan_result
            return redirect("attendance")
        except APIError as error:
            show_api_error(request, error)
            return redirect("attendance")
    scan_result = request.session.pop("last_attendance_scan", None)
    try:
        attendance_rows = api_request("api/attendance", query={"work_date": selected_date})
    except APIError as error:
        show_api_error(request, error)
        attendance_rows = []
    return render(
        request,
        "dashboard/attendance.html",
        {
            "attendance_rows": attendance_rows,
            "selected_date": selected_date,
            "scan_result": scan_result,
        },
    )


@role_required("admin", "staff", "viewer", write_roles=WRITE_ROLES)
def checkout(request):
    if request.method == "POST":
        employee_code = request.POST.get("employee_code", "").strip()
        try:
            scan_result = api_request(
                "api/attendance/checkout",
                method="POST",
                payload={"employee_code": employee_code},
            )
            request.session["last_attendance_checkout"] = scan_result
            return redirect("checkout")
        except APIError as error:
            show_api_error(request, error)
            return redirect("checkout")
    checkout_result = request.session.pop("last_attendance_checkout", None)
    try:
        checkout_rows = api_request("api/attendance/checkouts")
    except APIError as error:
        show_api_error(request, error)
        checkout_rows = []
    return render(
        request,
        "dashboard/checkout.html",
        {"checkout_rows": checkout_rows, "checkout_result": checkout_result},
    )


@role_required("admin", "staff", "viewer")
@require_GET
def attendance_reports(request):
    today = timezone.localdate().isoformat()
    filters = {
        "start_date": request.GET.get("start_date", today),
        "end_date": request.GET.get("end_date", today),
        "employee_code": request.GET.get("employee_code", "").strip(),
        "status": request.GET.get("status", ""),
    }
    query = {key: value for key, value in filters.items() if value}
    report_failed = False
    try:
        records = api_request("api/attendance/report", query=query)
    except APIError as error:
        show_api_error(request, error)
        records = []
        report_failed = True

    file_format = request.GET.get("export", "")
    if file_format and not report_failed:
        try:
            content, content_type, extension = export_rows(records, file_format)
        except ValueError:
            return HttpResponseBadRequest("Unsupported attendance export format")
        filename = f"attendance_report.{extension}"
        response = HttpResponse(content, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    return render(
        request,
        "dashboard/attendance_reports.html",
        {
            "records": records,
            "filters": filters,
            "status_labels": ATTENDANCE_STATUS_LABELS,
        },
    )


@role_required("admin", "staff", "viewer", write_roles=WRITE_ROLES)
def attendance_leave(request):
    selected_date = request.POST.get("work_date") or request.GET.get("date") or timezone.localdate().isoformat()
    if request.method == "POST":
        payload = {
            "employee_code": request.POST.get("employee_code", "").strip(),
            "work_date": selected_date,
            "status": request.POST.get("status", ""),
            "note": request.POST.get("note", "").strip(),
        }
        try:
            result = api_request("api/attendance/leave", method="POST", payload=payload)
            messages.success(request, f"Đã chấm phép {result['employee_code']} · {result['status']} ngày {result['work_date']}.")
        except APIError as error:
            show_api_error(request, error)
        return redirect(f"/attendance/leave/?date={selected_date}")

    try:
        records = api_request(
            "api/attendance/report",
            query={"start_date": selected_date, "end_date": selected_date},
        )
    except APIError as error:
        show_api_error(request, error)
        records = []
    leave_records = [
        {**row, "status_label": LEAVE_STATUS_LABELS[row["status"]]}
        for row in records
        if row["status"] in LEAVE_STATUS_LABELS
    ]
    return render(
        request,
        "dashboard/attendance_leave.html",
        {
            "leave_records": leave_records,
            "selected_date": selected_date,
            "status_labels": LEAVE_STATUS_LABELS,
        },
    )


@role_required("admin", "staff", "viewer", write_roles=WRITE_ROLES)
def handovers(request):
    if request.method == "POST":
        payload = {
            "title": request.POST.get("title", "").strip(),
            "line": request.POST.get("line", "").strip(),
            "owner": request.POST.get("owner", "").strip(),
            "details": request.POST.get("details", "").strip(),
            "deadline": request.POST.get("deadline") or None,
        }
        try:
            api_request("api/handovers", method="POST", payload=payload)
            messages.success(request, "Đã tạo mục bàn giao.")
            return redirect("handovers")
        except APIError as error:
            show_api_error(request, error)
    try:
        handover_rows = api_request("api/handovers")
    except APIError as error:
        show_api_error(request, error)
        handover_rows = []
    return render(request, "dashboard/handovers.html", {"handovers": handover_rows})


@role_required("admin", "staff")
@require_POST
def update_handover_status(request, handover_id):
    new_status = request.POST.get("status", "Done")
    try:
        api_request(f"api/handovers/{handover_id}", method="PATCH", payload={"status": new_status})
        messages.success(request, "Đã cập nhật trạng thái bàn giao.")
    except APIError as error:
        show_api_error(request, error)
    return redirect("handovers")


@role_required("admin", write_roles=("admin",))
def access_management(request):
    for role in ROLE_LABELS:
        Group.objects.get_or_create(name=role)

    if request.method == "POST":
        target_user = get_object_or_404(User, pk=request.POST.get("user_id"))
        selected_role = request.POST.get("role")
        if target_user.is_superuser:
            messages.error(request, "Tài khoản superuser luôn có toàn quyền và không thể đổi tại đây.")
        elif selected_role not in ROLE_LABELS:
            raise PermissionDenied
        elif (
            selected_role != "admin"
            and target_user.groups.filter(name="admin").exists()
            and not User.objects.filter(groups__name="admin", is_active=True).exclude(pk=target_user.pk).exists()
            and not User.objects.filter(is_superuser=True, is_active=True).exists()
        ):
            messages.error(request, "Không thể hạ quyền admin cuối cùng của hệ thống.")
        else:
            role_groups = Group.objects.filter(name__in=ROLE_LABELS)
            selected_group = Group.objects.get(name=selected_role)
            with transaction.atomic():
                target_user.groups.remove(*role_groups)
                target_user.groups.add(selected_group)
            messages.success(request, f"Đã gán quyền {ROLE_LABELS[selected_role]} cho {target_user.username}.")
        return redirect("access-management")

    users = User.objects.prefetch_related("groups").order_by("username")
    user_rows = []
    for user in users:
        assigned_roles = {group.name for group in user.groups.all()}.intersection(ROLE_LABELS)
        current_role = "admin" if user.is_superuser else next(
            (role for role in ("admin", "staff", "viewer") if role in assigned_roles),
            "",
        )
        user_rows.append({
            "user": user,
            "role": current_role,
            "role_label": ROLE_LABELS.get(current_role, ""),
        })
    return render(request, "dashboard/access.html", {"user_rows": user_rows, "roles": ROLE_LABELS})


@login_required
@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")
