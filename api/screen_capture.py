"""Explicit local desktop screenshot requests; no continuous screen capture."""

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from api.config_api import require_local_origin
from services.screen_capture import capture_main_display

router = APIRouter()


@router.post("/api/screen/capture")
async def capture_screen(request: Request, body: dict):
    require_local_origin(request)
    try:
        image = await run_in_threadpool(capture_main_display)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(
        image, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )
