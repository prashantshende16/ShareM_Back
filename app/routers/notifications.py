from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from app.services.notifications.push_notification_service import PushNotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class RegisterTokenRequest(BaseModel):
    fcm_token: str
    device_name: Optional[str] = "Android Device"
    platform: Optional[str] = "android"


class SendTestPushRequest(BaseModel):
    title: Optional[str] = "⚡ Test Surge Radar Alert"
    body: Optional[str] = "Testing FCM Push notification to Flutter app!"
    data: Optional[Dict[str, Any]] = None


@router.post("/register-token")
def register_fcm_token(payload: RegisterTokenRequest):
    """
    Registers an FCM device token from the Flutter app for push notifications.
    """
    return PushNotificationService.register_token(
        fcm_token=payload.fcm_token,
        device_name=payload.device_name or "Android Device",
        platform=payload.platform or "android"
    )


@router.get("/devices")
def get_registered_devices():
    """
    Returns list of registered mobile devices.
    """
    return {
        "status": "success",
        "devices": PushNotificationService.get_devices()
    }


@router.post("/send-test")
def send_test_push_notification(payload: SendTestPushRequest):
    """
    Triggers an immediate test push notification to all registered Flutter devices.
    """
    return PushNotificationService.send_push(
        title=payload.title or "⚡ Test Surge Radar Alert",
        body=payload.body or "Testing FCM Push notification to Flutter app!",
        data=payload.data or {"type": "TEST_ALERT"}
    )
