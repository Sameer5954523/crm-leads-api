from fastapi import FastAPI

from app.config import settings
from app.routers import auth, leads, users

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Lead-management CRM backend: authentication, role-based access, "
    "lead pipeline with validated status transitions, auto-routing and activity history.",
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(leads.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
