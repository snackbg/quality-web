from __future__ import annotations

import hmac
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field


APP_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("QUALITY_DB_PATH", APP_DIR / "data" / "quality.sqlite3"))
API_TOKEN = os.environ.get("QUALITY_API_TOKEN", "local-development-token")
LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

app = FastAPI(title="Quality Desk API", version="1.0.0")


def local_today() -> date:
    return datetime.now(LOCAL_TIMEZONE).date()


@contextmanager
def database():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                department TEXT NOT NULL DEFAULT '',
                position TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Active'
                    CHECK (status IN ('Active', 'Inactive')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
                work_date TEXT NOT NULL,
                status TEXT NOT NULL
                    CHECK (status IN ('Online', 'AL', 'UL', 'UAL', 'SL')),
                clock_in TEXT,
                clock_out TEXT,
                note TEXT NOT NULL DEFAULT '',
                UNIQUE (employee_id, work_date)
            );
            CREATE TABLE IF NOT EXISTS handovers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                line TEXT NOT NULL DEFAULT '',
                owner TEXT NOT NULL DEFAULT '',
                details TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Open'
                    CHECK (status IN ('Open', 'Done')),
                deadline TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        attendance_schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'attendance'"
        ).fetchone()["sql"]
        if "'Present'" in attendance_schema:
            connection.execute("ALTER TABLE attendance RENAME TO attendance_legacy")
            connection.execute(
                """
                CREATE TABLE attendance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
                    work_date TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('Online', 'AL', 'UL', 'UAL', 'SL')),
                    clock_in TEXT,
                    clock_out TEXT,
                    note TEXT NOT NULL DEFAULT '',
                    UNIQUE (employee_id, work_date)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO attendance (id, employee_id, work_date, status, clock_in, clock_out, note)
                SELECT id, employee_id, work_date,
                    CASE status
                        WHEN 'Present' THEN 'Online'
                        WHEN 'Annual leave' THEN 'AL'
                        WHEN 'Sick leave' THEN 'SL'
                        WHEN 'Absent' THEN 'UAL'
                        ELSE status
                    END,
                    clock_in, clock_out, note
                FROM attendance_legacy
                """
            )
            connection.execute("DROP TABLE attendance_legacy")
        attendance_columns = {row["name"] for row in connection.execute("PRAGMA table_info(attendance)").fetchall()}
        if "clock_out" not in attendance_columns:
            connection.execute("ALTER TABLE attendance ADD COLUMN clock_out TEXT")


@app.on_event("startup")
def startup_database() -> None:
    initialize_database()


class EmployeeCreate(BaseModel):
    employee_code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    department: str = Field(default="", max_length=100)
    position: str = Field(default="", max_length=100)


class AttendanceCreate(BaseModel):
    employee_id: int
    work_date: date
    status: Literal["Online", "AL", "UL", "UAL", "SL"]
    clock_in: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    note: str = Field(default="", max_length=500)


class AttendanceScan(BaseModel):
    employee_code: str = Field(min_length=1, max_length=50)


class AttendanceCheckoutScan(BaseModel):
    employee_code: str = Field(min_length=1, max_length=50)


class LeaveRecordCreate(BaseModel):
    employee_code: str = Field(min_length=1, max_length=50)
    work_date: date
    status: Literal["AL", "UL", "UAL", "SL"]
    note: str = Field(default="", max_length=500)


class HandoverCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    line: str = Field(default="", max_length=80)
    owner: str = Field(default="", max_length=100)
    details: str = Field(default="", max_length=1000)
    deadline: date | None = None


class HandoverStatusUpdate(BaseModel):
    status: Literal["Open", "Done"]


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    if x_api_key is None or not hmac.compare_digest(x_api_key, API_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/dashboard", dependencies=[Depends(require_api_key)])
def dashboard() -> dict[str, object]:
    today = local_today().isoformat()
    with database() as connection:
        employee_count = connection.execute(
            "SELECT COUNT(*) FROM employees WHERE status = 'Active'"
        ).fetchone()[0]
        attendance_rows = connection.execute(
            "SELECT status, COUNT(*) AS total FROM attendance WHERE work_date = ? GROUP BY status",
            (today,),
        ).fetchall()
        open_handovers = connection.execute(
            "SELECT COUNT(*) FROM handovers WHERE status = 'Open'"
        ).fetchone()[0]
        recent_handovers = connection.execute(
            "SELECT id, title, line, owner, status, deadline, created_at "
            "FROM handovers ORDER BY created_at DESC, id DESC LIMIT 5"
        ).fetchall()
    return {
        "today": today,
        "active_employees": employee_count,
        "attendance": {row["status"]: row["total"] for row in attendance_rows},
        "open_handovers": open_handovers,
        "recent_handovers": [dict(row) for row in recent_handovers],
    }


@app.get("/api/employees", dependencies=[Depends(require_api_key)])
def list_employees(q: str = Query(default="", max_length=100)) -> list[dict[str, object]]:
    search = f"%{q.strip()}%"
    with database() as connection:
        rows = connection.execute(
            "SELECT id, employee_code, name, department, position, status "
            "FROM employees WHERE employee_code LIKE ? OR name LIKE ? OR department LIKE ? "
            "ORDER BY name COLLATE NOCASE",
            (search, search, search),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/employees", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
def create_employee(payload: EmployeeCreate) -> dict[str, object]:
    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO employees (employee_code, name, department, position) VALUES (?, ?, ?, ?)",
                (payload.employee_code.strip(), payload.name.strip(), payload.department.strip(), payload.position.strip()),
            )
            employee_id = cursor.lastrowid
            row = connection.execute(
                "SELECT id, employee_code, name, department, position, status FROM employees WHERE id = ?",
                (employee_id,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Employee code already exists") from exc
    return dict(row)


@app.get("/api/attendance", dependencies=[Depends(require_api_key)])
def list_attendance(work_date: date | None = None) -> list[dict[str, object]]:
    selected_date = (work_date or local_today()).isoformat()
    with database() as connection:
        rows = connection.execute(
            "SELECT attendance.id, employees.employee_code, employees.name, employees.department, "
            "attendance.work_date, attendance.status, attendance.clock_in, attendance.clock_out, attendance.note "
            "FROM attendance JOIN employees ON employees.id = attendance.employee_id "
            "WHERE attendance.work_date = ? ORDER BY attendance.id DESC LIMIT 10",
            (selected_date,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/attendance/checkouts", dependencies=[Depends(require_api_key)])
def list_checkouts(work_date: date | None = None) -> list[dict[str, object]]:
    selected_date = (work_date or local_today()).isoformat()
    with database() as connection:
        rows = connection.execute(
            "SELECT attendance.id, employees.employee_code, employees.name, employees.department, "
            "attendance.work_date, attendance.status, attendance.clock_in, attendance.clock_out, attendance.note "
            "FROM attendance JOIN employees ON employees.id = attendance.employee_id "
            "WHERE attendance.work_date = ? AND attendance.clock_out IS NOT NULL "
            "ORDER BY attendance.clock_out DESC, attendance.id DESC LIMIT 10",
            (selected_date,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/attendance/report", dependencies=[Depends(require_api_key)])
def attendance_report(
    start_date: date | None = None,
    end_date: date | None = None,
    employee_code: str = Query(default="", max_length=50),
    attendance_status: Literal["Online", "AL", "UL", "UAL", "SL"] | None = Query(default=None, alias="status"),
) -> list[dict[str, object]]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ngày bắt đầu phải trước hoặc bằng ngày kết thúc")
    conditions = []
    parameters: list[object] = []
    if start_date:
        conditions.append("attendance.work_date >= ?")
        parameters.append(start_date.isoformat())
    if end_date:
        conditions.append("attendance.work_date <= ?")
        parameters.append(end_date.isoformat())
    if employee_code.strip():
        conditions.append("employees.employee_code LIKE ?")
        parameters.append(f"%{employee_code.strip()}%")
    if attendance_status:
        conditions.append("attendance.status = ?")
        parameters.append(attendance_status)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with database() as connection:
        rows = connection.execute(
            "SELECT attendance.id, employees.employee_code, employees.name, employees.department, "
            "attendance.work_date, attendance.status, attendance.clock_in, attendance.clock_out, attendance.note "
            "FROM attendance JOIN employees ON employees.id = attendance.employee_id "
            f"{where_clause} ORDER BY attendance.work_date DESC, employees.name COLLATE NOCASE",
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/attendance/scan", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
def scan_attendance(payload: AttendanceScan) -> dict[str, object]:
    employee_code = payload.employee_code.strip()
    scanned_at = datetime.now(LOCAL_TIMEZONE)
    work_date = scanned_at.date().isoformat()
    clock_in = scanned_at.strftime("%H:%M")
    try:
        with database() as connection:
            employee = connection.execute(
                "SELECT id, employee_code, name, department FROM employees "
                "WHERE employee_code = ? AND status = 'Active'",
                (employee_code,),
            ).fetchone()
            if employee is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nhân viên đang hoạt động với mã này")
            cursor = connection.execute(
                "INSERT INTO attendance (employee_id, work_date, status, clock_in) "
                "VALUES (?, ?, 'Online', ?)",
                (employee["id"], work_date, clock_in),
            )
            attendance_id = cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nhân viên đã chấm công hôm nay") from exc
    return {
        "id": attendance_id,
        "employee_id": employee["id"],
        "employee_code": employee["employee_code"],
        "name": employee["name"],
        "department": employee["department"],
        "work_date": work_date,
        "status": "Online",
        "clock_in": clock_in,
    }


@app.post("/api/attendance/leave", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
def create_leave_record(payload: LeaveRecordCreate) -> dict[str, object]:
    with database() as connection:
        employee = connection.execute(
            "SELECT id, employee_code, name, department FROM employees "
            "WHERE employee_code = ? AND status = 'Active'",
            (payload.employee_code.strip(),),
        ).fetchone()
        if employee is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nhân viên đang hoạt động với mã này")
        try:
            cursor = connection.execute(
                "INSERT INTO attendance (employee_id, work_date, status, note) VALUES (?, ?, ?, ?)",
                (employee["id"], payload.work_date.isoformat(), payload.status, payload.note.strip()),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nhân viên đã có dữ liệu chấm công trong ngày này") from exc
        row = connection.execute(
            "SELECT id, work_date, status, clock_in, clock_out, note FROM attendance WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return {
        "id": row["id"],
        "employee_code": employee["employee_code"],
        "name": employee["name"],
        "department": employee["department"],
        "work_date": row["work_date"],
        "status": row["status"],
        "clock_in": row["clock_in"],
        "clock_out": row["clock_out"],
        "note": row["note"],
    }


@app.post("/api/attendance/checkout", dependencies=[Depends(require_api_key)])
def checkout_attendance(payload: AttendanceCheckoutScan) -> dict[str, object]:
    employee_code = payload.employee_code.strip()
    scanned_at = datetime.now(LOCAL_TIMEZONE)
    work_date = scanned_at.date().isoformat()
    clock_out = scanned_at.strftime("%H:%M")
    with database() as connection:
        employee = connection.execute(
            "SELECT id, employee_code, name, department FROM employees "
            "WHERE employee_code = ? AND status = 'Active'",
            (employee_code,),
        ).fetchone()
        if employee is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nhân viên đang hoạt động với mã này")
        attendance = connection.execute(
            "SELECT id, status, clock_in, clock_out FROM attendance "
            "WHERE employee_id = ? AND work_date = ?",
            (employee["id"], work_date),
        ).fetchone()
        if attendance is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nhân viên chưa check-in đầu ca hôm nay")
        if attendance["clock_out"] is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nhân viên đã check-out hôm nay")
        update = connection.execute(
            "UPDATE attendance SET clock_out = ? WHERE id = ? AND clock_out IS NULL",
            (clock_out, attendance["id"]),
        )
        if update.rowcount == 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nhân viên đã check-out hôm nay")
        updated_attendance = connection.execute(
            "SELECT clock_out FROM attendance WHERE id = ?",
            (attendance["id"],),
        ).fetchone()
    return {
        "id": attendance["id"],
        "employee_id": employee["id"],
        "employee_code": employee["employee_code"],
        "name": employee["name"],
        "department": employee["department"],
        "work_date": work_date,
        "status": attendance["status"],
        "clock_in": attendance["clock_in"],
        "clock_out": updated_attendance["clock_out"],
    }


@app.post("/api/attendance", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
def record_attendance(payload: AttendanceCreate) -> dict[str, object]:
    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO attendance (employee_id, work_date, status, clock_in, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (payload.employee_id, payload.work_date.isoformat(), payload.status, payload.clock_in, payload.note.strip()),
            )
            row = connection.execute(
                "SELECT id, employee_id, work_date, status, clock_in, note FROM attendance WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Employee is unknown or already recorded for this date") from exc
    return dict(row)


@app.get("/api/handovers", dependencies=[Depends(require_api_key)])
def list_handovers(status_filter: Literal["Open", "Done"] | None = None) -> list[dict[str, object]]:
    with database() as connection:
        if status_filter:
            rows = connection.execute(
                "SELECT id, title, line, owner, details, status, deadline, created_at "
                "FROM handovers WHERE status = ? ORDER BY created_at DESC, id DESC",
                (status_filter,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT id, title, line, owner, details, status, deadline, created_at "
                "FROM handovers ORDER BY CASE status WHEN 'Open' THEN 0 ELSE 1 END, created_at DESC, id DESC"
            ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/handovers", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
def create_handover(payload: HandoverCreate) -> dict[str, object]:
    with database() as connection:
        cursor = connection.execute(
            "INSERT INTO handovers (title, line, owner, details, deadline) VALUES (?, ?, ?, ?, ?)",
            (payload.title.strip(), payload.line.strip(), payload.owner.strip(), payload.details.strip(), payload.deadline.isoformat() if payload.deadline else None),
        )
        row = connection.execute(
            "SELECT id, title, line, owner, details, status, deadline, created_at FROM handovers WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)


@app.patch("/api/handovers/{handover_id}", dependencies=[Depends(require_api_key)])
def update_handover(handover_id: int, payload: HandoverStatusUpdate) -> dict[str, object]:
    with database() as connection:
        cursor = connection.execute(
            "UPDATE handovers SET status = ? WHERE id = ?",
            (payload.status, handover_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handover not found")
        row = connection.execute(
            "SELECT id, title, line, owner, details, status, deadline, created_at FROM handovers WHERE id = ?",
            (handover_id,),
        ).fetchone()
    return dict(row)
