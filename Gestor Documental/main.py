import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.database import engine
from app import models
from app.routes import dashboard, documentos, importar, adjuntos, email_route

models.Base.metadata.create_all(bind=engine)

os.makedirs("uploads", exist_ok=True)

app = FastAPI(title="Sistema de Gestión Documental - OT6021")

app.include_router(dashboard.router)
app.include_router(documentos.router)
app.include_router(importar.router)
app.include_router(adjuntos.router)
app.include_router(email_route.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return FileResponse("static/index.html")
