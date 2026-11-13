import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import main


class QualityDeskAPITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database_path = main.DATABASE_PATH
        main.DATABASE_PATH = Path(self.temp_dir.name) / "test.sqlite3"
        self.client_context = TestClient(main.app)
        self.client = self.client_context.__enter__()
        self.headers = {"X-API-Key": main.API_TOKEN}

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        main.DATABASE_PATH = self.original_database_path
        self.temp_dir.cleanup()

    def test_api_requires_token(self):
        response = self.client.get("/api/employees")
        self.assertEqual(response.status_code, 401)

    def test_employee_attendance_and_handover_flow(self):
        employee_response = self.client.post(
            "/api/employees",
            headers=self.headers,
            json={
                "employee_code": "QA-001",
                "name": "Nguyen Minh Anh",
                "department": "Quality",
                "position": "Technician",
            },
        )
        self.assertEqual(employee_response.status_code, 201)
        employee_id = employee_response.json()["id"]

        attendance_response = self.client.post(
            "/api/attendance",
            headers=self.headers,
            json={
                "employee_id": employee_id,
                "work_date": main.local_today().isoformat(),
                "status": "Online",
                "clock_in": "08:00",
                "note": "",
            },
        )
        self.assertEqual(attendance_response.status_code, 201)
        dashboard = self.client.get("/api/dashboard", headers=self.headers).json()
        self.assertEqual(dashboard["active_employees"], 1)
        self.assertEqual(dashboard["attendance"]["Online"], 1)

        handover_response = self.client.post(
            "/api/handovers",
            headers=self.headers,
            json={"title": "Review inspection result", "line": "Line 2", "owner": "QA"},
        )
        self.assertEqual(handover_response.status_code, 201)
        handover_id = handover_response.json()["id"]
        close_response = self.client.patch(
            f"/api/handovers/{handover_id}",
            headers=self.headers,
            json={"status": "Done"},
        )
        self.assertEqual(close_response.json()["status"], "Done")
        dashboard = self.client.get("/api/dashboard", headers=self.headers).json()
        self.assertEqual(dashboard["open_handovers"], 0)

    def test_duplicate_employee_code_returns_conflict(self):
        payload = {"employee_code": "QA-002", "name": "Test Person"}
        first = self.client.post("/api/employees", headers=self.headers, json=payload)
        second = self.client.post("/api/employees", headers=self.headers, json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)

    def test_scan_records_server_time_and_rejects_duplicate(self):
        employee = self.client.post(
            "/api/employees",
            headers=self.headers,
            json={"employee_code": "SCAN-01", "name": "Scan Operator"},
        ).json()

        response = self.client.post(
            "/api/attendance/scan",
            headers=self.headers,
            json={"employee_code": "SCAN-01"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["employee_id"], employee["id"])
        self.assertEqual(response.json()["work_date"], main.local_today().isoformat())
        self.assertRegex(response.json()["clock_in"], r"^([01]\d|2[0-3]):[0-5]\d$")
        self.assertEqual(response.json()["status"], "Online")
        duplicate = self.client.post(
            "/api/attendance/scan",
            headers=self.headers,
            json={"employee_code": "SCAN-01"},
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_scan_rejects_unknown_employee(self):
        response = self.client.post(
            "/api/attendance/scan",
            headers=self.headers,
            json={"employee_code": "UNKNOWN"},
        )
        self.assertEqual(response.status_code, 404)

    def test_checkout_updates_existing_checkin_and_rejects_duplicate(self):
        employee = self.client.post(
            "/api/employees",
            headers=self.headers,
            json={"employee_code": "OUT-01", "name": "Checkout Operator"},
        ).json()
        checkin = self.client.post(
            "/api/attendance/scan",
            headers=self.headers,
            json={"employee_code": "OUT-01"},
        ).json()

        response = self.client.post(
            "/api/attendance/checkout",
            headers=self.headers,
            json={"employee_code": "OUT-01"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], checkin["id"])
        self.assertEqual(response.json()["employee_id"], employee["id"])
        self.assertEqual(response.json()["clock_in"], checkin["clock_in"])
        self.assertRegex(response.json()["clock_out"], r"^([01]\d|2[0-3]):[0-5]\d$")
        checkout_rows = self.client.get("/api/attendance/checkouts", headers=self.headers).json()
        self.assertEqual(len(checkout_rows), 1)
        self.assertEqual(checkout_rows[0]["clock_out"], response.json()["clock_out"])
        duplicate = self.client.post(
            "/api/attendance/checkout",
            headers=self.headers,
            json={"employee_code": "OUT-01"},
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_checkout_requires_existing_checkin(self):
        self.client.post(
            "/api/employees",
            headers=self.headers,
            json={"employee_code": "NO-IN-01", "name": "No Checkin"},
        )
        response = self.client.post(
            "/api/attendance/checkout",
            headers=self.headers,
            json={"employee_code": "NO-IN-01"},
        )
        self.assertEqual(response.status_code, 409)

    def test_attendance_report_filters_by_date_employee_and_leave_status(self):
        work_date = main.local_today().isoformat()
        first_employee = self.client.post(
            "/api/employees",
            headers=self.headers,
            json={"employee_code": "RPT-001", "name": "Report One"},
        ).json()
        second_employee = self.client.post(
            "/api/employees",
            headers=self.headers,
            json={"employee_code": "RPT-002", "name": "Report Two"},
        ).json()
        leave = self.client.post(
            "/api/attendance/leave",
            headers=self.headers,
            json={
                "employee_code": first_employee["employee_code"],
                "work_date": work_date,
                "status": "AL",
                "note": "Annual leave",
            },
        )
        self.assertEqual(leave.status_code, 201)
        self.client.post(
            "/api/attendance",
            headers=self.headers,
            json={
                "employee_id": second_employee["id"],
                "work_date": work_date,
                "status": "Online",
                "clock_in": "08:20",
                "note": "",
            },
        )
        report = self.client.get(
            "/api/attendance/report",
            headers=self.headers,
            params={
                "start_date": work_date,
                "end_date": work_date,
                "employee_code": "RPT-001",
                "status": "AL",
            },
        )
        self.assertEqual(report.status_code, 200)
        self.assertEqual(len(report.json()), 1)
        self.assertEqual(report.json()[0]["employee_code"], "RPT-001")
        invalid_range = self.client.get(
            "/api/attendance/report",
            headers=self.headers,
            params={"start_date": "2026-11-11", "end_date": "2026-11-10"},
        )
        self.assertEqual(invalid_range.status_code, 422)

    def test_initialize_migrates_interim_status_values_without_losing_times(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        connection = sqlite3.connect(legacy_path)
        connection.executescript(
            """
            CREATE TABLE employees (
                id INTEGER PRIMARY KEY,
                employee_code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                department TEXT NOT NULL DEFAULT '',
                position TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE attendance (
                id INTEGER PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id),
                work_date TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('Present', 'Annual leave', 'Sick leave', 'Absent')),
                clock_in TEXT,
                clock_out TEXT,
                note TEXT NOT NULL DEFAULT '',
                UNIQUE (employee_id, work_date)
            );
            INSERT INTO employees (id, employee_code, name) VALUES (1, 'MIG-001', 'Migrated Person');
            INSERT INTO attendance (id, employee_id, work_date, status, clock_in, clock_out)
            VALUES (1, 1, '2026-11-10', 'Present', '08:00', '17:00');
            """
        )
        connection.close()
        original_database_path = main.DATABASE_PATH
        try:
            main.DATABASE_PATH = legacy_path
            main.initialize_database()
            with main.database() as migrated:
                row = migrated.execute(
                    "SELECT status, clock_in, clock_out FROM attendance WHERE id = 1"
                ).fetchone()
            self.assertEqual(dict(row), {"status": "Online", "clock_in": "08:00", "clock_out": "17:00"})
        finally:
            main.DATABASE_PATH = original_database_path

    def test_leave_record_creates_only_once_for_employee_and_day(self):
        employee = self.client.post(
            "/api/employees",
            headers=self.headers,
            json={"employee_code": "LEAVE-01", "name": "Leave Employee"},
        ).json()
        work_date = main.local_today().isoformat()
        payload = {
            "employee_code": employee["employee_code"],
            "work_date": work_date,
            "status": "AL",
            "note": "Family appointment",
        }

        created = self.client.post("/api/attendance/leave", headers=self.headers, json=payload)

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["status"], "AL")
        self.assertEqual(created.json()["note"], "Family appointment")
        self.assertIsNone(created.json()["clock_in"])
        duplicate = self.client.post(
            "/api/attendance/leave",
            headers=self.headers,
            json={**payload, "status": "UL"},
        )
        self.assertEqual(duplicate.status_code, 409)
        report = self.client.get(
            "/api/attendance/report",
            headers=self.headers,
            params={"start_date": work_date, "end_date": work_date},
        ).json()
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["status"], "AL")


if __name__ == "__main__":
    unittest.main()
