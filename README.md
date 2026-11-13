# Quality Desk

Quality Desk is a separate implementation of the original operations site. Django serves the user interface and session-based login. FastAPI owns the business API and its SQLite database; Django never opens that database directly.

## Features

- Overview of active employees, today's attendance, and open handovers
- Employee directory with search and employee creation
- ID-scanner check-in with server-recorded Vietnam-local time, duplicate-scan protection, and the ten most recent records
- ID-scanner check-out that updates the original attendance row, preserves check-in time, and lists completed departures
- Today's check-in and completed checkout logs
- Attendance reports filtered by date range, employee ID, and Online/AL/UL/UAL/SL status, downloadable as XLSX, CSV, or PDF
- Chấm Phép records by employee ID, leave status, date, and reason; list only leave records for the selected date
- Handover creation, owner/deadline tracking, and completion
- Role-based UI with server-side access decorators, CSRF-protected write forms, and an API token between Django and FastAPI

## Run on Windows

Requires Python 3.10 or newer.

1. Run `setup.bat` from this folder.
2. Open one terminal here and run `run_api.bat`.
3. Open a second terminal here and run `run_web.bat`.
4. In a third terminal, create a Django account:

   ```powershell
   cd frontend
   ..\.venv\Scripts\python.exe manage.py createsuperuser
   ```

5. Sign in at http://127.0.0.1:8000/ with that account.

The API health endpoint is http://127.0.0.1:8001/health and its interactive documentation is http://127.0.0.1:8001/docs.

## Roles and access

Sign in as the Django superuser and open http://127.0.0.1:8000/access/. Create ordinary accounts in Django admin first, then assign each account one application role on the access page. A user without a role is denied access to operational pages. Superusers always retain full access.

- `admin`: view all operational sections, make changes, and assign application roles.
- `staff`: view and operate employee, check-in/check-out, Chấm Phép, and handover workflows; cannot manage roles.
- `viewer`: view the dashboard and operational lists, including Chấm Phép history; write forms and actions are hidden and direct write requests are denied.

Roles are Django auth groups. The `role_required` decorator in `frontend/dashboard/permissions.py` checks both page access and write permissions; templates use the same permission context to show only allowed navigation and actions.

## Tests

From the `backend` folder, run:

```powershell
..\.venv\Scripts\python.exe -m unittest test_main
```

## Data and configuration

The API database is created at `backend/data/quality.sqlite3`; Django login/session data is stored separately at `frontend/frontend.sqlite3`. Set `QUALITY_DB_PATH` to move the API database. Django calls the API at `QUALITY_API_URL` and sends `QUALITY_API_TOKEN`; both run scripts use a local development token. Change the token in both processes before exposing either service beyond localhost. Set a strong `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, and an explicit `DJANGO_ALLOWED_HOSTS` for any non-local deployment.

For check-in and check-out, add an active employee in the directory first. Both pages keep focus on the ID field; configure the scanner to type the employee code and send Enter after the scan. Check-in records the scan time and allows one entry per employee per local calendar day. Check-out requires a same-day check-in and fills the `clock_out` field on that existing attendance record without changing its check-in time or status. Each station prevents duplicate scans for its respective operation.

Attendance exports use the active report filters. Chấm Phép creates a new record for an active employee and selected date; it rejects a duplicate instead of overwriting existing attendance or clock-in/clock-out data. The list shows only leave records for the selected date. Status codes are `AL`, `UL`, `UAL`, and `SL`.
