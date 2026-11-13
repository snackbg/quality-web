import io
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook, load_workbook

from .api_client import APIError


def build_employee_upload(rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(("employee_code", "name", "department", "position"))
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return SimpleUploadedFile(
        "employee_batch.xlsx",
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class DashboardPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="operator", password="test-password")
        staff_group, _ = Group.objects.get_or_create(name="staff")
        self.user.groups.add(staff_group)

    def test_dashboard_redirects_to_login_for_anonymous_users(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/login/?next=/")

    @patch("dashboard.views.api_request", return_value=[])
    def test_sidebar_groups_hr_routes_and_marks_current_child(self, api_request):
        self.client.force_login(self.user)

        response = self.client.get("/attendance/reports/")

        self.assertContains(response, "Quản lý nhân sự")
        self.assertContains(response, 'id="sidebar-toggle"')
        self.assertContains(response, 'id="people-nav-links"')
        self.assertContains(response, 'href="/employees/"')
        self.assertContains(response, 'href="/attendance/"')
        self.assertContains(response, 'href="/checkout/"')
        self.assertContains(response, 'href="/attendance/reports/"')
        self.assertContains(response, 'href="/attendance/leave/"')
        self.assertContains(response, "has-active-child is-open")

    @patch("dashboard.views.api_request")
    def test_dashboard_renders_api_summary(self, api_request):
        api_request.side_effect = [
            {
                "today": "2026-11-10",
                "active_employees": 7,
                "attendance": {"Online": 5},
                "open_handovers": 2,
                "recent_handovers": [],
            },
            [
                {"work_date": "2026-11-10", "status": "Online"},
                {"work_date": "2026-11-10", "status": "AL"},
                {"work_date": "2026-11-09", "status": "Online"},
            ],
            [],
        ]
        self.client.force_login(self.user)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "7")
        self.assertContains(response, "5")
        self.assertContains(response, 'class="dashboard-balance"')
        self.assertContains(response, 'class="flow-chart"')
        self.assertContains(response, 'class="dashboard-table"')
        self.assertEqual(len(response.context["chart_days"]), 7)
        self.assertEqual(response.context["chart_days"][-1]["present"], 1)

    @patch("dashboard.views.api_request", return_value=[])
    def test_employee_attendance_and_handover_pages_render(self, api_request):
        self.client.force_login(self.user)
        for path in (
            "/employees/",
            "/attendance/",
            "/checkout/",
            "/attendance/reports/",
            "/attendance/leave/",
            "/handovers/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    @patch("dashboard.views.api_request", return_value=[])
    def test_employee_template_download_contains_import_columns(self, api_request):
        self.client.force_login(self.user)

        response = self.client.get("/employees/?download_template=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        workbook = load_workbook(io.BytesIO(response.content), read_only=True)
        self.assertEqual(
            tuple(cell.value for cell in workbook["Employees"][1]),
            ("employee_code", "name", "department", "position"),
        )
        self.assertIn("Guide", workbook.sheetnames)
        api_request.assert_not_called()

    @patch("dashboard.views.api_request")
    def test_employee_bulk_import_creates_valid_rows_and_reports_row_errors(self, api_request):
        api_request.side_effect = [{"id": 1}, {"id": 2}, []]
        self.client.force_login(self.user)
        upload = build_employee_upload([
            ("BULK-001", "Nguyen Van A", "Quality", "Technician"),
            ("BULK-001", "Duplicate ID", "Quality", "Technician"),
            ("BULK-002", "", "Quality", "Technician"),
            ("BULK-003", "Tran Thi B", "Production", "Operator"),
        ])

        response = self.client.post("/employees/", {"employee_file": upload}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Đã thêm 2 nhân viên từ file Excel")
        self.assertContains(response, "Dòng 3: employee_code")
        self.assertContains(response, "bị lặp trong file")
        self.assertContains(response, "Dòng 4: thiếu name")
        created_calls = [
            call for call in api_request.call_args_list
            if call.kwargs.get("method") == "POST"
        ]
        self.assertEqual(len(created_calls), 2)
        self.assertEqual(created_calls[0].kwargs["payload"]["employee_code"], "BULK-001")
        self.assertEqual(created_calls[1].kwargs["payload"]["employee_code"], "BULK-003")

    @patch("dashboard.views.api_request")
    def test_employee_bulk_import_reports_existing_database_code(self, api_request):
        api_request.side_effect = [
            {"id": 1},
            APIError("Employee code already exists (HTTP 409)"),
            [],
        ]
        self.client.force_login(self.user)
        upload = build_employee_upload([
            ("BULK-004", "Valid Employee", "Quality", "Technician"),
            ("EXISTING", "Duplicate Employee", "Quality", "Technician"),
        ])

        response = self.client.post("/employees/", {"employee_file": upload}, follow=True)

        self.assertContains(response, "Đã thêm 1 nhân viên từ file Excel")
        self.assertContains(response, "Dòng 3:")
        self.assertContains(response, "Employee code already exists")

    @patch("dashboard.views.api_request")
    def test_scanning_id_redirects_and_shows_saved_checkin(self, api_request):
        api_request.side_effect = [
            {
                "employee_code": "QA-001",
                "name": "Nguyen Minh Anh",
                "department": "Quality",
                "work_date": "2026-11-10",
                "clock_in": "08:15",
            },
            [],
        ]
        self.client.force_login(self.user)

        response = self.client.post("/attendance/", {"employee_code": "QA-001"})

        self.assertRedirects(response, "/attendance/", fetch_redirect_response=False)
        api_request.assert_any_call(
            "api/attendance/scan",
            method="POST",
            payload={"employee_code": "QA-001"},
        )
        page = self.client.get(response.url)
        self.assertContains(page, "Nguyen Minh Anh")
        self.assertContains(page, "08:15")

    @patch("dashboard.views.api_request")
    def test_scanning_id_redirects_and_shows_saved_checkout(self, api_request):
        api_request.side_effect = [
            {
                "employee_code": "QA-001",
                "name": "Nguyen Minh Anh",
                "department": "Quality",
                "work_date": "2026-11-10",
                "clock_in": "08:15",
                "clock_out": "17:30",
            },
            [],
        ]
        self.client.force_login(self.user)

        response = self.client.post("/checkout/", {"employee_code": "QA-001"})

        self.assertRedirects(response, "/checkout/", fetch_redirect_response=False)
        api_request.assert_any_call(
            "api/attendance/checkout",
            method="POST",
            payload={"employee_code": "QA-001"},
        )
        page = self.client.get(response.url)
        self.assertContains(page, "Nguyen Minh Anh")
        self.assertContains(page, "17:30")

    @patch("dashboard.views.api_request")
    def test_viewer_can_read_but_cannot_write_or_manage_roles(self, api_request):
        viewer = User.objects.create_user(username="reader", password="test-password")
        viewer_group, _ = Group.objects.get_or_create(name="viewer")
        viewer.groups.add(viewer_group)
        api_request.return_value = []
        self.client.force_login(viewer)

        attendance_page = self.client.get("/attendance/")
        self.assertEqual(attendance_page.status_code, 200)
        self.assertNotContains(attendance_page, "attendance-scan-form")
        self.assertNotContains(attendance_page, "Phân quyền")
        self.assertEqual(self.client.post("/attendance/", {"employee_code": "QA-001"}).status_code, 403)
        self.assertEqual(self.client.get("/attendance/reports/").status_code, 200)
        status_page = self.client.get("/attendance/leave/")
        self.assertEqual(status_page.status_code, 200)
        self.assertNotContains(status_page, "leave-entry-form")
        self.assertEqual(
            self.client.post(
                "/attendance/leave/",
                {"employee_code": "QA-001", "work_date": "2026-11-10", "status": "AL"},
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get("/access/").status_code, 403)
        api_request.assert_any_call("api/attendance/report", query={"start_date": "2026-11-10", "end_date": "2026-11-10"})

    def test_admin_can_assign_one_role_to_another_user(self):
        admin_group, _ = Group.objects.get_or_create(name="admin")
        self.user.groups.add(admin_group)
        self.client.force_login(self.user)
        target = User.objects.create_user(username="new-staff", password="test-password")

        response = self.client.get("/access/")
        self.assertEqual(response.status_code, 200)
        response = self.client.post("/access/", {"user_id": target.pk, "role": "viewer"})

        self.assertRedirects(response, "/access/")
        target.refresh_from_db()
        self.assertEqual(list(target.groups.values_list("name", flat=True)), ["viewer"])

    def test_last_admin_cannot_remove_their_own_admin_role(self):
        admin_group, _ = Group.objects.get_or_create(name="admin")
        self.user.groups.add(admin_group)
        self.client.force_login(self.user)

        response = self.client.post("/access/", {"user_id": self.user.pk, "role": "viewer"}, follow=True)

        self.assertContains(response, "Không thể hạ quyền admin cuối cùng")
        self.assertTrue(self.user.groups.filter(name="admin").exists())

    @patch("dashboard.views.api_request")
    def test_leave_form_creates_record_for_selected_day(self, api_request):
        api_request.return_value = {
            "employee_code": "QA-001",
            "status": "AL",
            "work_date": "2026-11-10",
        }
        self.client.force_login(self.user)

        response = self.client.post(
            "/attendance/leave/",
            {
                "employee_code": "QA-001",
                "work_date": "2026-11-10",
                "status": "AL",
                "note": "Annual leave",
            },
        )

        self.assertRedirects(response, "/attendance/leave/?date=2026-11-10", fetch_redirect_response=False)
        api_request.assert_called_once_with(
            "api/attendance/leave",
            method="POST",
            payload={
                "employee_code": "QA-001",
                "work_date": "2026-11-10",
                "status": "AL",
                "note": "Annual leave",
            },
        )

    @patch("dashboard.views.api_request")
    def test_report_filters_are_forwarded_to_api(self, api_request):
        api_request.return_value = []
        self.client.force_login(self.user)
        response = self.client.get(
            "/attendance/reports/",
            {
                "start_date": "2026-11-01",
                "end_date": "2026-11-10",
                "employee_code": "QA-00",
                "status": "AL",
            },
        )
        self.assertEqual(response.status_code, 200)
        api_request.assert_called_once_with(
            "api/attendance/report",
            query={
                "start_date": "2026-11-01",
                "end_date": "2026-11-10",
                "employee_code": "QA-00",
                "status": "AL",
            },
        )

    @patch("dashboard.views.api_request")
    def test_report_exports_csv_xlsx_and_pdf(self, api_request):
        api_request.return_value = [
            {
                "employee_code": "QA-001",
                "name": "Nguyen Minh Anh",
                "department": "Quality",
                "work_date": "2026-11-10",
                "status": "AL",
                "clock_in": "08:10",
                "clock_out": "17:30",
                "note": "Annual leave",
            }
        ]
        self.client.force_login(self.user)
        base_query = "?start_date=2026-11-10&end_date=2026-11-10&employee_code=QA-001&status=AL&export="

        csv_response = self.client.get("/attendance/reports/" + base_query + "csv")
        self.assertEqual(csv_response["Content-Type"], "text/csv; charset=utf-8")
        self.assertTrue(csv_response.content.startswith(b"\xef\xbb\xbf"))

        xlsx_response = self.client.get("/attendance/reports/" + base_query + "xlsx")
        workbook = load_workbook(io.BytesIO(xlsx_response.content), read_only=True)
        self.assertEqual(workbook.active["A2"].value, "QA-001")

        pdf_response = self.client.get("/attendance/reports/" + base_query + "pdf")
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")
        self.assertTrue(pdf_response.content.startswith(b"%PDF-"))

    @patch("dashboard.views.api_request")
    def test_cham_phep_lists_only_leave_records_for_selected_day(self, api_request):
        api_request.return_value = [
            {"employee_code": "QA-001", "name": "Leave Person", "work_date": "2026-11-10", "status": "AL", "note": "Annual leave"},
            {"employee_code": "QA-002", "name": "Present Person", "work_date": "2026-11-10", "status": "Online", "note": ""},
        ]
        self.client.force_login(self.user)

        response = self.client.get("/attendance/leave/?date=2026-11-10")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Leave Person")
        self.assertContains(response, "AL - Nghỉ phép năm")
        self.assertNotContains(response, "Present Person")

    def test_previous_attendance_status_url_redirects_to_cham_phep(self):
        self.client.force_login(self.user)
        response = self.client.get("/attendance/status/")
        self.assertRedirects(response, "/attendance/leave/", fetch_redirect_response=False)
