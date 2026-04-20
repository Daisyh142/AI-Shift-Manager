# Manual Verification Checklist

Frontend URL: `http://localhost:5173`  
Backend URL: `http://127.0.0.1:8000`

## Prerequisites

- Backend running with `uvicorn backend.main:app --reload`
- Frontend running with `npm run dev` in `frontend/`
- Seed data available (`POST /seed`) and demo users:
  - owner: `owner@demo.com` / `demo`
  - employee: `employee@demo.com` / `demo`

## Feature 1: Time formatting (ET, 12-hour)

1. Login as owner and generate/load a schedule.
2. Verify shift cells in owner schedule preview show `h:mm AM/PM` format (example `9:00 AM - 5:00 PM`).
3. Login as employee and verify the same format in both `My Schedule` and `Team Schedule`.
4. Confirm no seconds are shown anywhere in shift time text.

## Feature 2: Coverage requests workflow

1. Login as employee and open dashboard.
2. In `Request Shift Coverage`, pick a shift and submit.
3. Confirm item appears under `My Coverage Requests` with `pending` status.
4. Login as owner and confirm request appears under `Coverage Requests`.
5. Approve with and without selecting a cover employee.
6. Re-login as employee and confirm status updates to `approved` and selected cover employee (when chosen).
7. Create another request, deny as owner, and verify employee sees `denied`.

## Feature 3: More/Less hours workflow

1. Login as employee and submit a pay-period hours request (0-80).
2. Confirm item appears under `My Hours Requests` with `pending`.
3. Login as owner and confirm request appears under `Hours Change Requests`.
4. Approve request.
5. Generate a schedule for the same pay period.
6. Confirm employee status updates immediately and scheduling behavior reflects approved preference on regeneration.

## API contract smoke checks

- `POST /coverage-requests` (employee only)
- `GET /coverage-requests/mine` (employee only)
- `GET /coverage-requests/pending` (owner only)
- `PATCH /coverage-requests/{id}/decision` (owner only)
- `POST /hours-requests` (employee only)
- `GET /hours-requests/mine` (employee only)
- `GET /hours-requests/pending` (owner only)
- `PATCH /hours-requests/{id}/decision` (owner only)
