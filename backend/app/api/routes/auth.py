"""
POST /signup, POST /login, POST /logout
"""
from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup")
async def signup():
    raise NotImplementedError


@router.post("/login")
async def login():
    raise NotImplementedError


@router.post("/logout")
async def logout():
    raise NotImplementedError
