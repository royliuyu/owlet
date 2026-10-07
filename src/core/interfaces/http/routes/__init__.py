"""API routers."""

from fastapi import APIRouter

from core.interfaces.http.routes import chat, collections, documents, google, index, system

router = APIRouter()
router.include_router(system.router)
router.include_router(collections.router)
router.include_router(documents.router)
router.include_router(google.router)
router.include_router(index.router)
router.include_router(chat.router)
