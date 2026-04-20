from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from .db import init_db

load_dotenv()

from .routers.auth import router as auth_router
from .routers.availability import router as availability_router
from .routers.analytics import router as analytics_router
from .routers.ai import router as ai_router
from .routers.coverage_requests import router as coverage_requests_router
from .routers.employees import router as employees_router
from .routers.hours_requests import router as hours_requests_router
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
app.include_router(coverage_requests_router)
app.include_router(employees_router)
app.include_router(hours_requests_router)
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

@app.post("/seed")
def run_seed(authorization: str = Header(default="")):
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env in {"prod", "production"}:
        raise HTTPException(status_code=403, detail="seed_disabled_in_production")

    from .models import User
    from .routers.auth import get_current_user_from_header, pwd_ctx
    from .db import engine
    from .seed import seed as run_seed_fn
    from sqlmodel import Session, SQLModel, select

    if app_env not in {"dev", "development", "local", "test"}:
        with Session(engine) as auth_session:
            current_user = get_current_user_from_header(
                session=auth_session,
                authorization=authorization,
            )
            if current_user.role != "owner":
                raise HTTPException(
                    status_code=403,
                    detail={"code": "forbidden", "message": "Owner role is required"},
                )

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    run_seed_fn()

    with Session(engine) as session:
        if not session.exec(select(User).where(User.email == "owner@demo.com")).first():
            session.add(User(
                email="owner@demo.com",
                hashed_password=pwd_ctx.hash("demo"),
                role="owner",
                employee_id="m1",
            ))

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
