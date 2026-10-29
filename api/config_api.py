import io
import os
import shutil
from typing import Literal
from urllib.parse import urlsplit

import aiofiles
import orjson
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

import window_manager
from core.config import settings
from core.env_utils import env_manager
from core.key_utils import resolve_provider_keys
from core.paths import data_dir
from services.desktop_sync import desktop_sync
from services.llm_service import verify_provider_connection
from services.vision_service import verify_vision_provider_connection

router = APIRouter()

@router.get("/api/profile")
async def get_default_profile():
    """Read optional personal defaults from the app's writable data directory."""
    path = data_dir() / "profile.json"
    if not path.is_file():
        return {}
    async with aiofiles.open(path, "rb") as f:
        return orjson.loads(await f.read())

class TransparencyRequest(BaseModel):
    transparency: float  # 0.0 to 1.0

class TransparencyPercentRequest(BaseModel):
    percent: int  # 0 to 100

class ProviderVerifyRequest(BaseModel):
    name: str
    model: str

class SaveProvidersRequest(BaseModel):
    providers: list

class SaveKeyRequest(BaseModel):
    key: str

class DesktopDisplayRequest(BaseModel):
    enabled: bool

class DesktopCommandRequest(BaseModel):
    session_id: str = Field(min_length=1)
    command: Literal[
        "toggle_mic_mute",
        "toggle_universal_mute",
        "switch_preset",
        "toggle_vision_mode",
        "switch_vision_model",
        "capture_screenshot",
        "process_screenshots",
        "reset_screenshot_queue",
        "reset_interview",
        "end_interview",
        "manual_question",
    ]
    preset_key: Literal["primary", "secondary", "auto"] = "primary"
    text: str = Field(default="", max_length=20000)


class DesktopAppearanceRequest(BaseModel):
    action: Literal["opacity", "click_through", "hide", "move"]
    opacity: Literal[0.4, 0.7, 1.0] = 1.0
    direction: Literal["up", "down", "left", "right"] = "up"


def require_local_origin(request: Request):
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme != request.url.scheme or parsed.netloc != request.url.netloc:
            raise HTTPException(
                status_code=403, detail="Desktop controls require the local Aura page."
            )


@router.post("/api/desktop/command")
async def desktop_command(command: DesktopCommandRequest, request: Request):
    from api.session_manager import session_manager

    require_local_origin(request)
    success = await session_manager.route_shortcut(command.model_dump())
    if not success:
        raise HTTPException(
            status_code=409,
            detail="This Chrome session is no longer connected. Reconnect before using its controls.",
        )
    return {"success": True}


@router.post("/api/desktop/appearance")
async def desktop_appearance(command: DesktopAppearanceRequest, request: Request):
    require_local_origin(request)
    manager = window_manager.window_manager
    if command.action == "opacity":
        success = manager.set_transparency(command.opacity)
    elif command.action == "click_through":
        if not manager.is_ghost_mode and not manager.can_restore_click_through():
            raise HTTPException(
                status_code=409,
                detail="Enable Aura in macOS Accessibility and restart it first. Option+X must be available to restore window controls.",
            )
        success = manager.toggle_ghost_mode()
    elif command.action == "hide":
        manager.toggle_visibility()
        success = True
    else:
        moves = {"up": (0, -20), "down": (0, 20), "left": (-20, 0), "right": (20, 0)}
        success = manager.move_window(*moves[command.direction])
    return {"success": success}


@router.get("/api/desktop/appearance")
async def desktop_appearance_state():
    return window_manager.window_manager.get_click_through_state()


@router.post("/api/window/desktop-display")
async def configure_desktop_display(request: DesktopDisplayRequest):
    if request.enabled and not desktop_sync.readiness()["ready"]:
        raise HTTPException(status_code=409, detail=desktop_sync.readiness()["message"])
    return {
        "success": window_manager.window_manager.set_desktop_display(request.enabled)
    }


@router.get("/api/desktop/status")
async def desktop_status():
    return {
        **desktop_sync.readiness(),
        "shortcuts_ready": window_manager.window_manager.can_restore_click_through(),
    }


@router.get("/api/config")
async def get_config():
    """
    Returns frontend configuration values including DEV_MODE.
    This allows JavaScript to access centralized config values.
    """
    return {
        "DEV_MODE": settings.DEV_MODE,
        "LOG_LEVEL": settings.LOG_LEVEL,
        "CAPTURE_PROTECTION_ENABLED": not settings.DEV_MODE
    }

@router.get("/api/ai-providers")
async def get_ai_providers():
    """
    Reads the ai_providers.json file and returns a list of providers
    to the frontend, excluding sensitive API keys.
    """
    try:
        if not os.path.exists("ai_providers.json"):
            if os.path.exists("ai_providers.example.json"):
                print("📝 ai_providers.json not found, creating from example...")
                shutil.copy("ai_providers.example.json", "ai_providers.json")
            else:
                raise HTTPException(status_code=404, detail="ai_providers.json and example not found")

        async with aiofiles.open("ai_providers.json", "rb") as f:
            file_content = await f.read()
            providers = orjson.loads(file_content)
        
        # Sanitize the data before sending to the client
        client_safe_providers = [
            {
                "name": p.get("name"),
                "models": p.get("models", []),
                "visionModels": p.get("visionModels", []),
                "supportsVision": p.get("supportsVision", False),
                # Images this provider accepts in a single request. The
                # screenshot queue caps itself to this so a batch is never
                # assembled that the selected vision model will reject.
                "maxImages": p.get("maxImages"),
                "defaultPrimary": p.get("defaultPrimary", False),
                "defaultSecondary": p.get("defaultSecondary", False),
                "defaultVisionPrimary": p.get("defaultVisionPrimary", False),
                "defaultVisionSecondary": p.get("defaultVisionSecondary", False),
                "defaultModel": p.get("defaultModel"),
                "defaultVisionModel": p.get("defaultVisionModel"),
                # Keep legacy default for backward compatibility
                "default": p.get("defaultPrimary", False)
            }
            for p in providers
        ]
        return client_safe_providers
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="ai_providers.json not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading provider config: {e}")

@router.get("/api/ai-providers/full")
async def get_ai_providers_full():
    """
    Returns the full ai_providers.json INCLUDING API keys.
    Used for the advanced configuration UI.
    """
    try:
        if not os.path.exists("ai_providers.json"):
             if os.path.exists("ai_providers.example.json"):
                shutil.copy("ai_providers.example.json", "ai_providers.json")
             else:
                return []
                
        async with aiofiles.open("ai_providers.json", "rb") as f:
            file_content = await f.read()
            return orjson.loads(file_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading full provider config: {e}")

@router.post("/api/save-ai-providers")
async def save_ai_providers(request: SaveProvidersRequest):
    """Saves the full provider configuration to ai_providers.json."""
    try:
        async with aiofiles.open("ai_providers.json", "wb") as f:
            await f.write(orjson.dumps(request.providers, option=orjson.OPT_INDENT_2))
        return {"success": True, "message": "AI Providers saved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving provider config: {e}")

@router.get("/api/deepgram-key")
async def get_deepgram_key():
    """Retrieves the current DEEPGRAM_API_KEY from .env."""
    key = env_manager.get_value("DEEPGRAM_API_KEY")
    return {"key": key or ""}

@router.post("/api/save-deepgram-key")
async def save_deepgram_key(request: SaveKeyRequest):
    """Save the key for verification and new transcription sessions."""
    key = request.key.strip()
    if any(character in key for character in ('\r', '\n', '"')):
        raise HTTPException(status_code=400, detail="Paste only the Deepgram key secret, without quotes or line breaks.")
    try:
        success = env_manager.update_key("DEEPGRAM_API_KEY", key)
        if success:
            settings.DEEPGRAM_API_KEY = key
            return {"success": True, "message": "Deepgram API key saved successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to update .env file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving Deepgram key: {e}")

@router.post("/api/verify-provider")
async def verify_ai_provider(request: ProviderVerifyRequest):
    """
    Verifies a connection to the selected AI provider.
    Tries all available apiKeys if the first one fails.
    """
    try:
        async with aiofiles.open("ai_providers.json", "rb") as f:
            file_content = await f.read()
            providers = orjson.loads(file_content)
        
        provider_config = next((p for p in providers if p["name"] == request.name), None)

        if not provider_config:
            raise HTTPException(status_code=404, detail=f"Provider '{request.name}' not found.")

        # Get all usable keys (blank/placeholder entries filtered out)
        api_keys = resolve_provider_keys(provider_config)
        if not api_keys:
            print(f"⚠️ No usable API key configured for {request.name}")
            return {"success": False, "error": "No API key configured for this provider."}

        # Try each key until one works
        for i, key in enumerate(api_keys):
            is_valid = await verify_provider_connection(
                base_url=provider_config.get("baseURL"),
                api_key=key,
                model_name=request.model
            )
            if is_valid:
                return {"success": True}
            print(f"⚠️ Key {i+1}/{len(api_keys)} failed for {request.name}, trying next...")
        
        return {"success": False}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to verify provider: {e}")

@router.post("/api/verify-vision-provider")
async def verify_vision_ai_provider(request: ProviderVerifyRequest):
    """
    Verifies a connection to the selected vision AI provider.
    Tries all available apiKeys if the first one fails.
    """
    try:
        async with aiofiles.open("ai_providers.json", "rb") as f:
            file_content = await f.read()
            providers = orjson.loads(file_content)
        
        provider_config = next((p for p in providers if p["name"] == request.name), None)

        if not provider_config:
            raise HTTPException(status_code=404, detail=f"Provider '{request.name}' not found.")

        if not provider_config.get("supportsVision", False):
            raise HTTPException(status_code=400, detail=f"Provider '{request.name}' does not support vision.")

        # Check if model exists in visionModels and extract model config (handle both string and object formats)
        vision_models = provider_config.get("visionModels", [])
        model_config = None
        
        for vision_model in vision_models:
            if isinstance(vision_model, str) and vision_model == request.model:
                model_config = {"modelName": vision_model}  # Normalize to dict
                break
            elif isinstance(vision_model, dict) and vision_model.get("modelName") == request.model:
                model_config = vision_model
                break
        
        if not model_config:
            raise HTTPException(status_code=400, detail=f"Model '{request.model}' is not a vision model for '{request.name}'.")

        # Get all usable keys (blank/placeholder entries filtered out)
        api_keys = resolve_provider_keys(provider_config)
        if not api_keys:
            print(f"⚠️ No usable vision API key configured for {request.name}")
            return {"success": False, "error": "No API key configured for this provider."}

        # Try each key until one works
        for i, key in enumerate(api_keys):
            is_valid = await verify_vision_provider_connection(
                base_url=provider_config.get("baseURL"),
                api_key=key,
                model_name=request.model,
                request_params=model_config.get("requestParams")
            )
            if is_valid:
                return {"success": True}
            print(f"⚠️ Vision key {i+1}/{len(api_keys)} failed for {request.name}, trying next...")
        
        return {"success": False}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to verify vision provider: {e}")

@router.get("/api/transparency")
async def get_transparency():
    """Get current window transparency information"""
    return window_manager.get_transparency_info()

@router.post("/api/transparency")
async def set_transparency(request: TransparencyRequest):
    """Set window transparency (0.0 = transparent, 1.0 = opaque)"""
    success = window_manager.set_app_transparency(request.transparency)
    if success:
        return {
            "success": True,
            "transparency": request.transparency,
            "message": f"Transparency set to {request.transparency*100:.0f}%"
        }
    else:
        raise HTTPException(status_code=400, detail="Failed to set transparency")

@router.post("/api/transparency/percent")
async def set_transparency_percent(request: TransparencyPercentRequest):
    """Set window transparency as percentage (0 = transparent, 100 = opaque)"""
    success = window_manager.set_app_transparency_percent(request.percent)
    if success:
        return {
            "success": True,
            "percent": request.percent,
            "transparency": request.percent / 100.0,
            "message": f"Transparency set to {request.percent}%"
        }
    else:
        raise HTTPException(status_code=400, detail="Failed to set transparency")

@router.post("/api/transparency/presets/transparent")
async def make_transparent():
    """Make window 60% transparent (40% opacity) - good for interviews"""
    success = window_manager.make_app_transparent()
    if success:
        return {"success": True, "message": "Window set to interview mode (40% opacity)"}
    else:
        raise HTTPException(status_code=400, detail="Failed to set transparency")

@router.post("/api/transparency/presets/semi-transparent")
async def make_semi_transparent():
    """Make window semi-transparent (70% opacity)"""
    success = window_manager.make_app_semi_transparent()
    if success:
        return {"success": True, "message": "Window set to semi-transparent (70% opacity)"}
    else:
        raise HTTPException(status_code=400, detail="Failed to set transparency")

@router.post("/api/transparency/presets/opaque")
async def make_opaque():
    """Make window fully opaque (100% opacity)"""
    success = window_manager.make_app_opaque()
    if success:
        return {"success": True, "message": "Window set to opaque (100% opacity)"}
    else:
        raise HTTPException(status_code=400, detail="Failed to set transparency")



@router.post("/api/extract-pdf")
async def extract_pdf(file: UploadFile = File(...)):
    """
    Extract plain text from an uploaded PDF (used by onboarding PDF upload).
    Returns { filename, text, pages, chars }.
    """
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    raw = await file.read()
    # Guard against very large uploads (25 MB).
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF too large (max 25 MB).")

    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        parts = []
        for page in reader.pages:
            txt = (page.extract_text() or "").strip()
            if txt:
                parts.append(txt)
        text = "\n\n".join(parts).strip()
        # Normalize common typographic ligatures that PDFs embed as single glyphs.
        for lig, repl in (("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff"), ("ﬃ", "ffi"),
                          ("ﬄ", "ffl"), ("ﬅ", "ft"), ("ﬆ", "st")):
            text = text.replace(lig, repl)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read PDF: {str(exc)[:200]}")

    if not text:
        raise HTTPException(
            status_code=422,
            detail="No selectable text found — this PDF may be scanned/image-only.",
        )

    return {"filename": filename, "text": text, "pages": len(reader.pages), "chars": len(text)}
