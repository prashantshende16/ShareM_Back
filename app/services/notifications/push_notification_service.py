import os
import json
import time
import logging
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger(__name__)

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
TOKENS_FILE = os.path.join(UPLOADS_DIR, "fcm_tokens.json")
PUSH_HISTORY_FILE = os.path.join(UPLOADS_DIR, "push_history.json")

# Firebase configuration from google-services.json
FCM_SERVER_KEY = os.getenv("FCM_SERVER_KEY", "AIzaSyA2cYae1z21ovfn3WnfwdF3wxQeNs6-o9A")
FCM_LEGACY_URL = "https://fcm.googleapis.com/fcm/send"


class PushNotificationService:
    """
    Firebase Cloud Messaging (FCM) Push Notification Service for Flutter App.
    Sends real-time Surge Radar alerts and notifications whenever new trade signals
    are detected on the backend.
    """

    @classmethod
    def _load_tokens(cls) -> List[Dict[str, Any]]:
        if not os.path.exists(TOKENS_FILE):
            return []
        try:
            with open(TOKENS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load FCM tokens: {e}")
            return []

    @classmethod
    def _save_tokens(cls, tokens: List[Dict[str, Any]]):
        try:
            os.makedirs(UPLOADS_DIR, exist_ok=True)
            with open(TOKENS_FILE, "w") as f:
                json.dump(tokens, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save FCM tokens: {e}")

    @classmethod
    def register_token(cls, fcm_token: str, device_name: str = "Android", platform: str = "android") -> Dict[str, Any]:
        """Registers a device FCM token from the Flutter mobile app."""
        if not fcm_token or not fcm_token.strip():
            return {"status": "error", "message": "FCM token is required"}

        token = fcm_token.strip()
        tokens = cls._load_tokens()

        existing = next((t for t in tokens if t.get("token") == token), None)
        now_ts = int(time.time())

        if existing:
            existing["device_name"] = device_name
            existing["platform"] = platform
            existing["last_active"] = now_ts
        else:
            tokens.append({
                "token": token,
                "device_name": device_name,
                "platform": platform,
                "registered_at": now_ts,
                "last_active": now_ts
            })

        cls._save_tokens(tokens)
        logger.info(f"Registered FCM device token for {device_name} ({platform})")
        return {
            "status": "success",
            "message": "Token registered successfully",
            "total_devices": len(tokens)
        }

    @classmethod
    def get_devices(cls) -> List[Dict[str, Any]]:
        return cls._load_tokens()

    @classmethod
    def _log_history(cls, title: str, body: str, data: Dict[str, Any], results: Dict[str, Any]):
        try:
            os.makedirs(UPLOADS_DIR, exist_ok=True)
            history = []
            if os.path.exists(PUSH_HISTORY_FILE):
                with open(PUSH_HISTORY_FILE, "r") as f:
                    history = json.load(f)
            history.insert(0, {
                "title": title,
                "body": body,
                "data": data,
                "results": results,
                "timestamp": int(time.time())
            })
            with open(PUSH_HISTORY_FILE, "w") as f:
                json.dump(history[:100], f, indent=2)
        except Exception as e:
            logger.warning(f"Could not log push history: {e}")

    @classmethod
    def send_surge_radar_notification(cls, suggestion: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatches a high-priority push notification to Flutter devices
        when a new Surge Radar momentum setup is identified.
        """
        sym = suggestion.get("symbol", "INDEX")
        strike = suggestion.get("strike_price", "")
        opt = suggestion.get("option_type", "")
        ltp = suggestion.get("current_ltp", suggestion.get("entry_price", 0))
        entry = suggestion.get("entry_price", 0)
        t1 = suggestion.get("target_1", 0)
        sl = suggestion.get("stop_loss", 0)
        badge = suggestion.get("surge_badge", "Sudden Move")

        title = f"🔥 {sym} {strike} {opt} | {badge}"
        body = f"LTP: ₹{ltp} | Buy Entry: ₹{entry} | Target 1: ₹{t1} | SL: ₹{sl}"

        data_payload = {
            "type": "SURGE_RADAR_ALERT",
            "id": str(suggestion.get("id", "")),
            "symbol": str(sym),
            "strike_price": str(strike),
            "option_type": str(opt),
            "entry_price": str(entry),
            "current_ltp": str(ltp),
            "target_1": str(t1),
            "target_2": str(suggestion.get("target_2", "")),
            "stop_loss": str(sl),
            "surge_pct": str(suggestion.get("surge_pct", "")),
            "click_action": "FLUTTER_NOTIFICATION_CLICK"
        }

        return cls.send_push(title=title, body=body, data=data_payload)

    @classmethod
    def send_push(cls, title: str, body: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Sends push notification to:
        1. Topic subscribers (/topics/surge_radar_alerts)
        2. All registered device tokens
        """
        data = data or {}
        tokens = [t["token"] for t in cls._load_tokens() if t.get("token")]

        headers = {
            "Authorization": f"key={FCM_SERVER_KEY}",
            "Content-Type": "application/json"
        }

        results = {
            "topic_sent": False,
            "direct_tokens_count": len(tokens),
            "success_count": 0,
            "failure_count": 0,
            "errors": []
        }

        # 1. Send to Topic
        topic_payload = {
            "to": "/topics/surge_radar_alerts",
            "priority": "high",
            "notification": {
                "title": title,
                "body": body,
                "sound": "default",
                "android_channel_id": "surge_radar_channel"
            },
            "data": data
        }

        try:
            r = requests.post(FCM_LEGACY_URL, headers=headers, json=topic_payload, timeout=5)
            results["topic_sent"] = r.status_code == 200
            if r.status_code != 200:
                results["errors"].append(f"Topic error: {r.status_code} - {r.text}")
        except Exception as e:
            results["errors"].append(f"Topic send failed: {e}")

        # 2. Send to all registered devices directly
        for token in tokens:
            device_payload = {
                "to": token,
                "priority": "high",
                "notification": {
                    "title": title,
                    "body": body,
                    "sound": "default",
                    "android_channel_id": "surge_radar_channel"
                },
                "data": data
            }
            try:
                r = requests.post(FCM_LEGACY_URL, headers=headers, json=device_payload, timeout=5)
                if r.status_code == 200:
                    results["success_count"] += 1
                else:
                    results["failure_count"] += 1
            except Exception as e:
                results["failure_count"] += 1
                results["errors"].append(f"Device send error: {e}")

        cls._log_history(title, body, data, results)
        logger.info(f"Push notification sent: {title} | {results}")
        return {
            "status": "success",
            "results": results
        }
