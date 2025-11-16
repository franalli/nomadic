import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.tile_service import search_tiles

from .config import settings
from .schemas import TilesSearchRequest, TilesSearchResponse

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "Nomadic Backend")

app = FastAPI(title=APP_NAME)

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # add prod frontend origin later, e.g. "https://app.yourdomain.com"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "env": settings.env,
    }


@app.post("/v1/tiles/search", response_model=TilesSearchResponse)
def tiles_search(req: TilesSearchRequest):
    return search_tiles(req)
