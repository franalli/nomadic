from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .schemas import TilesSearchRequest, TilesSearchResponse
from .tile_service import search_tiles
from dotenv import load_dotenv
import os

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "Nomadic Backend")

app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": APP_NAME}

@app.post("/v1/tiles/search", response_model=TilesSearchResponse)
def tiles_search(req: TilesSearchRequest):
    return search_tiles(req)
