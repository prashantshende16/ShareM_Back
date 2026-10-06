import os
import uuid
from typing import Tuple
from fastapi import UploadFile, HTTPException
from app.config import settings

def ensure_upload_dir():
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

async def save_uploaded_screenshot(file: UploadFile) -> Tuple[str, str, str]:
    """
    Validates and saves uploaded screenshot.
    Returns (file_path, file_name, mime_type)
    """
    ensure_upload_dir()
    
    # 1. Validate extension
    filename = file.filename or "screenshot.png"
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type .{ext}. Allowed types: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )

    # 2. Generate secure name
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    file_path = os.path.join(settings.UPLOAD_DIR, unique_filename)

    # 3. Stream write and check size
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    total_bytes = 0

    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum allowed size of {settings.MAX_FILE_SIZE_MB}MB"
        )

    with open(file_path, "wb") as f:
        f.write(content)

    mime_type = file.content_type or f"image/{ext}"
    return file_path, unique_filename, mime_type

def remove_screenshot_file(file_path: str):
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
