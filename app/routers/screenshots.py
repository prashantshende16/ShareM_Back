import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Analysis, AnalysisScreenshot
from app.schemas import ScreenshotResponse
from app.utils.file_upload import save_uploaded_screenshot, remove_screenshot_file

router = APIRouter(tags=["Screenshots"])

@router.post("/analyses/{id}/screenshots", response_model=ScreenshotResponse)
async def upload_screenshot(
    id: int,
    file: UploadFile = File(...),
    timeframe: str = Form("15 Minute"),
    db: Session = Depends(get_db)
):
    analysis = db.query(Analysis).filter(Analysis.id == id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    file_path, unique_name, mime_type = await save_uploaded_screenshot(file)

    screenshot = AnalysisScreenshot(
        analysis_id=id,
        timeframe=timeframe,
        file_path=file_path,
        file_name=unique_name,
        mime_type=mime_type
    )
    db.add(screenshot)
    db.commit()
    db.refresh(screenshot)

    return ScreenshotResponse(
        id=screenshot.id,
        analysis_id=screenshot.analysis_id,
        timeframe=screenshot.timeframe,
        file_path=screenshot.file_path,
        file_name=screenshot.file_name,
        mime_type=screenshot.mime_type,
        url=f"/uploads/{screenshot.file_name}",
        created_at=screenshot.created_at
    )

@router.delete("/screenshots/{id}")
def delete_screenshot(id: int, db: Session = Depends(get_db)):
    screenshot = db.query(AnalysisScreenshot).filter(AnalysisScreenshot.id == id).first()
    if not screenshot:
        raise HTTPException(status_code=404, detail="Screenshot not found")

    remove_screenshot_file(screenshot.file_path)
    db.delete(screenshot)
    db.commit()
    return {"message": f"Screenshot {id} deleted successfully"}
