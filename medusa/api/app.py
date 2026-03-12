from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from medusa.api.routers import tasks, screenshot

app = FastAPI(title="Medusa API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router)
app.include_router(screenshot.router)
