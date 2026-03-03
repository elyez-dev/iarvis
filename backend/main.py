from fastapi import FastAPI
from api.routers import frontend

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Server is running"}

app.include_router(frontend.router, prefix="/frontend")