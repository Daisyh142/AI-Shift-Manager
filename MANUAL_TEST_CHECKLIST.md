# Manual Test Checklist for WorkForYou Application

**Frontend URL:** http://127.0.0.1:5173  
**Backend URL:** http://127.0.0.1:8000

## Prerequisites

- Backend server running on port 8000
- Frontend dev server running on port 5173
- Browser console open to watch runtime errors

---

## Core E2E Verification (Owner + Employee)

### 1) Home page loads

**Action:** Open `http://127.0.0.1:5173`.

**Expected:**
- Sign-in card is visible
- Email + password fields visible
- `Try Demo Data` button visible

Result: [ PASS / FAIL ]
Notes:

---

### 2) Demo login (owner)

**Action:** Click `Try Demo Data`.

**Expected:**
- App seeds backend demo data
- Redirect to `/dashboard`
- Owner dashboard shows `Schedule Actions`

Result: [ PASS / FAIL ]
Notes:

---

### 3) Owner generates schedule

**Action:** Click `Generate Schedule`.

**Expected:**
- Current run id appears (`Current schedule run ID: ...`)
- Schedule preview section updates

Result: [ PASS / FAIL ]
Notes:

---

### 4) Owner publishes schedule

**Action:** Click `Publish`.

**Expected:**
- No crash
- Success toast appears
- Schedule status remains usable from dashboard

Result: [ PASS / FAIL ]
Notes:

---

### 5) Owner requests page

**Action:** Open sidebar `Requests`.

**Expected:**
- `/requests` opens
- `All Requests` section renders
- No blank screen

Result: [ PASS / FAIL ]
Notes:

---

### 6) Owner logout

**Action:** Click `Log out`.

**Expected:**
- Redirect to `/`
- Sign-in screen visible again

Result: [ PASS / FAIL ]
Notes:

---

### 7) Employee login

**Action:** Login with:
- Email: `employee@demo.com`
- Password: `demo`

**Expected:**
- Redirect to `/dashboard`
- Employee dashboard visible (`My Schedule`, stats cards)

Result: [ PASS / FAIL ]
Notes:

---

### 8) Employee dashboard stats

**Action:** Inspect dashboard cards.

**Expected:**
- `Weekly Required Hours`
- `Weekly Max Hours`
- `PTO Balance`

Result: [ PASS / FAIL ]
Notes:

---

### 9) Employee team schedule

**Action:** Open `Team Schedule` in sidebar.

**Expected:**
- `/team-schedule` opens
- Team schedule renders, OR clear message if no published schedule exists

Result: [ PASS / FAIL ]
Notes:

---

### 10) Employee submits time-off request

**Action:**
1. Open `My Requests`
2. Choose a date at least 14 days in the future
3. Submit request

**Expected:**
- Request submission succeeds
- Request appears in list and/or success toast appears

Result: [ PASS / FAIL ]
Notes:

---

## Summary

- Total tests: 10
- Passed: ___
- Failed: ___
- Overall: [ PASS / FAIL ]

## Backend API contract references

- `POST /seed`
- `POST /auth/login`
- `GET /auth/me`
- `POST /schedules/generate?mode=optimized` with body `{ "week_start_date": "YYYY-MM-DD" }`
- `POST /schedules/{schedule_run_id}/publish`
- `GET /schedules/latest?status=published`
- `GET /time-off/requests`
- `POST /time-off/requests`
- `POST /time-off/requests/{request_id}/approve`
- `POST /time-off/requests/{request_id}/deny`
