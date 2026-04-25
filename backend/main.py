from fastapi import FastAPI
from api.routers import frontend, n8n

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Server is running"}

app.include_router(frontend.router, prefix="/frontend")
app.include_router(n8n.router, prefix="/n8n")