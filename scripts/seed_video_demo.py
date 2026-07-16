"""
Ad-hoc seed script for the TE-16 demo video capture session.
Populates the local sqlite DB with a synthetic admin session + realistic
pipeline run history so the real frontend renders a populated UI for
screenshotting. Not part of the product — disposable, local-only.
"""
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from app.core.database import engine
from app.models import (
    Pipeline,
    PipelineRun,
    RunStatus,
    User,
    UserRole,
    UserStatus,
    Session as SessionModel,
    SystemSettings,
)
from app.auth.auth import create_access_token, create_session

PIPELINES = [
    "heavy_deps",
    "notebook_example",
    "py311_demo",
    "py312_demo",
    "test_failing",
    "test_logging",
    "test_simple",
    "test_with_requirements",
    "nightly-etl",
    "invoice-sync",
    "ml-feature-pipeline",
]

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

now = datetime.now(timezone.utc)

with Session(engine) as session:
    # --- Admin user + long-lived session token for headless capture ---
    user = session.exec(select(User).where(User.username == "demo-admin")).first()
    if not user:
        user = User(
            username="demo-admin",
            email="demo-admin@fastflow.local",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        session.commit()
        session.refresh(user)

    token = create_access_token(user.username, expires_delta=timedelta(hours=6))
    create_session(session, user, token)
    print("AUTH_TOKEN=" + token)

    settings_row = session.get(SystemSettings, 1)
    if not settings_row:
        settings_row = SystemSettings(id=1)
    settings_row.is_setup_completed = True
    session.add(settings_row)
    session.commit()

    # --- Pipeline run history (last 14 days, several runs per pipeline) ---
    existing = session.exec(select(PipelineRun)).all()
    if not existing:
        for name in PIPELINES:
            total = 0
            success = 0
            failed = 0
            n_runs = random.randint(6, 14)
            for i in range(n_runs):
                started = now - timedelta(
                    days=random.uniform(0, 13), hours=random.uniform(0, 23)
                )
                duration = random.uniform(2.5, 48.0)
                finished = started + timedelta(seconds=duration)

                if name == "test_failing":
                    status = RunStatus.FAILED
                elif name == "test_logging":
                    status = random.choices(
                        [RunStatus.SUCCESS, RunStatus.WARNING], weights=[0.7, 0.3]
                    )[0]
                else:
                    status = random.choices(
                        [RunStatus.SUCCESS, RunStatus.FAILED],
                        weights=[0.88, 0.12],
                    )[0]

                total += 1
                if status == RunStatus.SUCCESS:
                    success += 1
                elif status == RunStatus.FAILED:
                    failed += 1

                run_id = uuid4()
                log_path = LOG_DIR / f"{name}_{run_id}.log"
                log_path.write_text(
                    f"[{started.isoformat()}] fastflow: syncing {name}\n"
                    f"[{started.isoformat()}] uv sync (0 image builds)\n"
                    f"[{started.isoformat()}] running {name}/main.py in isolated container\n"
                    + (
                        f"[{finished.isoformat()}] ERROR: pipeline failed (exit 1)\n"
                        if status == RunStatus.FAILED
                        else f"[{finished.isoformat()}] pipeline finished successfully\n"
                    )
                )

                run = PipelineRun(
                    id=run_id,
                    pipeline_name=name,
                    status=status,
                    log_file=str(log_path),
                    started_at=started,
                    finished_at=finished,
                    exit_code=0 if status == RunStatus.SUCCESS else 1,
                    triggered_by=random.choice(["manual", "scheduler", "webhook", "manual"]),
                    setup_duration=round(random.uniform(0.8, 6.5), 2),
                    git_sha="a1b2c3d",
                    git_branch="main",
                    git_commit_message="Update pipeline config",
                )
                session.add(run)

            pipeline = session.get(Pipeline, name)
            if not pipeline:
                pipeline = Pipeline(pipeline_name=name)
            pipeline.total_runs = total
            pipeline.successful_runs = success
            pipeline.failed_runs = failed
            session.add(pipeline)

        session.commit()
        print(f"Seeded {len(PIPELINES)} pipelines with run history.")
    else:
        print("Run history already present, skipped.")
