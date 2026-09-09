"""
File di avvio del server (FastAPI).
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import accounting, agent, alerts, auth, azioni_pendenti, dashboard, data_explorer, integrations, team, views
from app.core.config import settings
from app.services import scheduler
from app import models  # noqa: F401  (registra i modelli su Base.metadata, letto da Alembic)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Cortex che agisce da solo (18 agosto 2026): il ciclo di controllo
    # periodico (Segnalazioni + riepilogo mattutino, vedi services/notifiche.py
    # e services/scheduler.py) parte una volta con il server e vive finché
    # vive il processo — cancellato pulitamente allo spegnimento.
    task = asyncio.create_task(scheduler.loop_controllo())
    yield
    task.cancel()


app = FastAPI(title="Cortex Enterprise API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(agent.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")
app.include_router(data_explorer.router, prefix="/api")
app.include_router(accounting.router, prefix="/api")
app.include_router(team.router, prefix="/api")
app.include_router(views.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(azioni_pendenti.router, prefix="/api")

# Lo schema del database è gestito da Alembic (vedi backend/alembic/versions/),
# non più da un Base.metadata.create_all() all'avvio: prima di lanciare il
# server (anche in sviluppo) esegui `alembic upgrade head` dentro backend/.


@app.get("/")
def root() -> dict[str, str]:
    """Health check di base."""
    return {"status": "ok", "service": "Cortex Enterprise API"}
