from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from .constraints import validate_assignments
from .db import init_db
from .fairness import calculate_fairness
from .scheduler import generate_greedy_schedule
from .schemas import GenerateScheduleRequest, ScheduleResponse

load_dotenv()

from .routers.auth import router as auth_router
from .routers.availability import router as availability_router
from .routers.analytics import router as analytics_router
from .routers.ai import router as ai_router
from .routers.employees import router as employees_router
from .routers.job_roles import router as job_roles_router
from .routers.metrics import router as metrics_router
from .routers.pto import router as pto_router
from .routers.schedules import router as schedules_router
from .routers.shifts import router as shifts_router
from .routers.time_off import router as time_off_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)

# Allow the Vite dev server (and any localhost origin) to call our API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(ai_router)
app.include_router(employees_router)
app.include_router(availability_router)
app.include_router(analytics_router)
app.include_router(pto_router)
app.include_router(time_off_router)
app.include_router(job_roles_router)
app.include_router(metrics_router)
app.include_router(shifts_router)
app.include_router(schedules_router)

@app.get("/")
def health_check():
    return {"status": "ok", "app": "workforyou"}

@app.post("/schedules/generate", response_model=ScheduleResponse)
def generate_schedule(request: GenerateScheduleRequest) -> ScheduleResponse:
    assignments = generate_greedy_schedule(
        employees=request.employees,
        availability=request.availability,
        pto=request.pto,
        shifts=request.shifts,
    )
    violations = validate_assignments(
        employees=request.employees,
        availability=request.availability,
        pto=request.pto,
        shifts=request.shifts,
        assignments=assignments,
    )
    
    fairness_scores = calculate_fairness(
        employees=request.employees,
        shifts=request.shifts,
        assignments=assignments
    )
    
    overall_score = sum(s.percentage for s in fairness_scores) / len(fairness_scores) if fairness_scores else 0
    
    return ScheduleResponse(
        week_start_date=request.week_start_date,
        assignments=assignments,
        violations=violations,
        fairness_scores=fairness_scores,
        overall_score=overall_score,
    )


@app.post("/seed")
def run_seed():
    """
    Populate the database with demo data and create demo user accounts.

    Drops and recreates all tables first so the endpoint is safely re-runnable.
    Returns credentials for the seeded owner and employee accounts so the
    frontend "Try Demo" button can log in immediately.
    """
    from .models import User
    from .routers.auth import pwd_ctx
    from .db import engine
    from .seed import seed as run_seed_fn
    from sqlmodel import Session, SQLModel, select

    # Reset all tables so seed is idempotent
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    run_seed_fn()

    with Session(engine) as session:
        # Create demo owner account linked to the manager employee
        if not session.exec(select(User).where(User.email == "owner@demo.com")).first():
            session.add(User(
                email="owner@demo.com",
                hashed_password=pwd_ctx.hash("demo"),
                role="owner",
                employee_id="m1",
            ))

        # Create demo employee account linked to Riley Server
        if not session.exec(select(User).where(User.email == "employee@demo.com")).first():
            session.add(User(
                email="employee@demo.com",
                hashed_password=pwd_ctx.hash("demo"),
                role="employee",
                employee_id="s1",
            ))

        session.commit()

    return {
        "status": "seeded",
        "demo_accounts": [
            {"email": "owner@demo.com", "password": "demo", "role": "owner"},
            {"email": "employee@demo.com", "password": "demo", "role": "employee"},
        ],
    }
