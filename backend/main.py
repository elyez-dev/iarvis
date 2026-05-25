from fastapi import FastAPI
from api.routers import frontend, n8n
from core.database import init_database
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

app = FastAPI()


@app.on_event("startup")
async def startup():
    await init_database()


@app.get("/")
async def root():
    return {"message": "Server is running"}

app.include_router(frontend.router, prefix="/frontend")
app.include_router(n8n.router, prefix="/n8n")