import time
import struct
import hmac
import hashlib
import base64
import logging
import datetime
from typing import Dict, Any, List, Optional
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Angel One Index and Stock Symbol Token Registry
ANGEL_ONE_TOKENS: Dict[str, Dict[str, str]] = {
    # Indices (NSE)
    "NIFTY": {"exchange": "NSE", "symboltoken": "99926000", "tradingsymbol": "Nifty 50"},
    "NIFTY 50": {"exchange": "NSE", "symboltoken": "99926000", "tradingsymbol": "Nifty 50"},
    "NIFTY50": {"exchange": "NSE", "symboltoken": "99926000", "tradingsymbol": "Nifty 50"},
    "^NSEI": {"exchange": "NSE", "symboltoken": "99926000", "tradingsymbol": "Nifty 50"},
    "BANKNIFTY": {"exchange": "NSE", "symboltoken": "99926009", "tradingsymbol": "Nifty Bank"},
    "BANK NIFTY": {"exchange": "NSE", "symboltoken": "99926009", "tradingsymbol": "Nifty Bank"},
    "^NSEBANK": {"exchange": "NSE", "symboltoken": "99926009", "tradingsymbol": "Nifty Bank"},
    "FINNIFTY": {"exchange": "NSE", "symboltoken": "99926037", "tradingsymbol": "Nifty Fin Services"},
    "FIN NIFTY": {"exchange": "NSE", "symboltoken": "99926037", "tradingsymbol": "Nifty Fin Services"},
    "NIFTY_FIN_SERVICE.NS": {"exchange": "NSE", "symboltoken": "99926037", "tradingsymbol": "Nifty Fin Services"},
    "MIDCPNIFTY": {"exchange": "NSE", "symboltoken": "99926074", "tradingsymbol": "NIFTY MID SELECT"},
    "MIDCAP NIFTY": {"exchange": "NSE", "symboltoken": "99926074", "tradingsymbol": "NIFTY MID SELECT"},
    "NIFTY_MID_SELECT.NS": {"exchange": "NSE", "symboltoken": "99926074", "tradingsymbol": "NIFTY MID SELECT"},
    "SENSEX": {"exchange": "BSE", "symboltoken": "99919000", "tradingsymbol": "SENSEX"},
    "^BSESN": {"exchange": "BSE", "symboltoken": "99919000", "tradingsymbol": "SENSEX"},
    
    # Heavyweight Stocks (NSE)
    "RELIANCE": {"exchange": "NSE", "symboltoken": "2885", "tradingsymbol": "RELIANCE-EQ"},
    "RELIANCE.NS": {"exchange": "NSE", "symboltoken": "2885", "tradingsymbol": "RELIANCE-EQ"},
    "HDFCBANK": {"exchange": "NSE", "symboltoken": "1333", "tradingsymbol": "HDFCBANK-EQ"},
    "HDFCBANK.NS": {"exchange": "NSE", "symboltoken": "1333", "tradingsymbol": "HDFCBANK-EQ"},
    "ICICIBANK": {"exchange": "NSE", "symboltoken": "4963", "tradingsymbol": "ICICIBANK-EQ"},
    "ICICIBANK.NS": {"exchange": "NSE", "symboltoken": "4963", "tradingsymbol": "ICICIBANK-EQ"},
    "INFY": {"exchange": "NSE", "symboltoken": "1594", "tradingsymbol": "INFY-EQ"},
    "INFY.NS": {"exchange": "NSE", "symboltoken": "1594", "tradingsymbol": "INFY-EQ"},
    "TCS": {"exchange": "NSE", "symboltoken": "11536", "tradingsymbol": "TCS-EQ"},
    "TCS.NS": {"exchange": "NSE", "symboltoken": "11536", "tradingsymbol": "TCS-EQ"},
    "SBIN": {"exchange": "NSE", "symboltoken": "3045", "tradingsymbol": "SBIN-EQ"},
    "SBIN.NS": {"exchange": "NSE", "symboltoken": "3045", "tradingsymbol": "SBIN-EQ"},
    "KOTAKBANK": {"exchange": "NSE", "symboltoken": "1922", "tradingsymbol": "KOTAKBANK-EQ"},
    "KOTAKBANK.NS": {"exchange": "NSE", "symboltoken": "1922", "tradingsymbol": "KOTAKBANK-EQ"},
    "AXISBANK": {"exchange": "NSE", "symboltoken": "5900", "tradingsymbol": "AXISBANK-EQ"},
    "AXISBANK.NS": {"exchange": "NSE", "symboltoken": "5900", "tradingsymbol": "AXISBANK-EQ"},
    "LT": {"exchange": "NSE", "symboltoken": "11483", "tradingsymbol": "LT-EQ"},
    "LT.NS": {"exchange": "NSE", "symboltoken": "11483", "tradingsymbol": "LT-EQ"},
    "ITC": {"exchange": "NSE", "symboltoken": "1660", "tradingsymbol": "ITC-EQ"},
    "ITC.NS": {"exchange": "NSE", "symboltoken": "1660", "tradingsymbol": "ITC-EQ"},
}

INTERVAL_MAP = {
    "1m": "ONE_MINUTE",
    "5m": "FIVE_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "1h": "ONE_HOUR",
    "1d": "ONE_DAY"
}

def generate_totp(secret: str) -> str:
    """
    Pure Python RFC 6238 TOTP generator.
    Works with standard 32-char Base32 Google Authenticator secrets.
    """
    secret = secret.replace(" ", "").upper()
    missing_padding = len(secret) % 8
    if missing_padding != 0:
        secret += '=' * (8 - missing_padding)
    key = base64.b32decode(secret, casefold=True)
    counter = int(time.time() // 30)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[19] & 15
    code = (struct.unpack(">I", digest[offset:offset+4])[0] & 0x7FFFFFFF) % 1000000
    return f"{code:06d}"

class AngelOneService:
    BASE_URL = "https://apiconnect.angelone.in"
    _session_token: Optional[str] = None
    _token_expiry: float = 0.0
    _client_code: Optional[str] = None

    @classmethod
    def is_configured(cls) -> bool:
        return bool(
            getattr(settings, "ANGEL_ONE_API_KEY", "") and
            getattr(settings, "ANGEL_ONE_CLIENT_CODE", "") and
            getattr(settings, "ANGEL_ONE_PIN", "") and
            getattr(settings, "ANGEL_ONE_TOTP_KEY", "")
        )

    @classmethod
    def get_headers(cls, jwt_token: Optional[str] = None) -> Dict[str, str]:
        api_key = getattr(settings, "ANGEL_ONE_API_KEY", "")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "106.193.147.98",
            "X-MACAddress": "fe80::",
            "X-PrivateKey": api_key,
        }
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token.replace('Bearer ', '')}"
        return headers

    @classmethod
    def login_sync(cls, force: bool = False) -> Dict[str, Any]:
        """Synchronous version of login."""
        now = time.time()
        if not force and cls._session_token and now < cls._token_expiry:
            return {"status": True, "token": cls._session_token, "cached": True}

        api_key = getattr(settings, "ANGEL_ONE_API_KEY", "").strip()
        client_code = getattr(settings, "ANGEL_ONE_CLIENT_CODE", "").strip()
        pin = getattr(settings, "ANGEL_ONE_PIN", "").strip()
        totp_key = getattr(settings, "ANGEL_ONE_TOTP_KEY", "").strip()

        if not (api_key and client_code and pin and totp_key):
            return {
                "status": False,
                "message": "Angel One credentials incomplete. Please configure API Key, Client Code, PIN, and TOTP Key in Settings."
            }

        try:
            totp_code = generate_totp(totp_key)
        except Exception as e:
            return {"status": False, "message": f"Invalid TOTP Key format: {e}"}

        login_url = f"{cls.BASE_URL}/rest/auth/angelbroking/user/v1/loginByPassword"
        payload = {
            "clientcode": client_code,
            "password": pin,
            "totp": totp_code
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(login_url, json=payload, headers=cls.get_headers())
                data = res.json()

                if data.get("status") is True and data.get("data"):
                    jwt_token = data["data"].get("jwtToken")
                    cls._session_token = jwt_token
                    cls._token_expiry = now + (5 * 3600)
                    cls._client_code = client_code
                    logger.info("Angel One SmartAPI login successful.")
                    return {
                        "status": True,
                        "token": jwt_token,
                        "feed_token": data["data"].get("feedToken"),
                        "message": "Login successful"
                    }
                else:
                    err_msg = data.get("message") or data.get("errorcode") or "Unknown error"
                    logger.warning(f"Angel One login failed: {err_msg}")
                    return {"status": False, "message": err_msg}
        except Exception as e:
            logger.error(f"Angel One login request error: {e}")
            return {"status": False, "message": f"Network error during Angel One login: {str(e)}"}

    @classmethod
    async def login(cls, force: bool = False) -> Dict[str, Any]:
        """Asynchronous version of login."""
        return cls.login_sync(force=force)

    @classmethod
    def resolve_token(cls, symbol: str) -> Optional[Dict[str, str]]:
        clean = symbol.strip().upper()
        if clean in ANGEL_ONE_TOKENS:
            return ANGEL_ONE_TOKENS[clean]
        no_space = clean.replace(" ", "")
        if no_space in ANGEL_ONE_TOKENS:
            return ANGEL_ONE_TOKENS[no_space]
        return None

    @classmethod
    def get_ltp_sync(cls, symbol: str) -> Optional[Dict[str, Any]]:
        """Synchronously fetches live LTP for a symbol."""
        token_info = cls.resolve_token(symbol)
        if not token_info:
            return None

        login_res = cls.login_sync()
        if not login_res.get("status"):
            return None

        url = f"{cls.BASE_URL}/rest/secure/angelbroking/order/v1/getLtpData"
        payload = {
            "exchange": token_info["exchange"],
            "tradingsymbol": token_info["tradingsymbol"],
            "symboltoken": token_info["symboltoken"]
        }

        try:
            with httpx.Client(timeout=6.0) as client:
                res = client.post(url, json=payload, headers=cls.get_headers(cls._session_token))
                data = res.json()
                if data.get("status") is True and data.get("data"):
                    d = data["data"]
                    return {
                        "symbol": symbol,
                        "tradingsymbol": d.get("tradingsymbol"),
                        "ltp": float(d.get("ltp", 0.0)),
                        "open": float(d.get("open", 0.0)),
                        "high": float(d.get("high", 0.0)),
                        "low": float(d.get("low", 0.0)),
                        "close": float(d.get("close", 0.0)),
                        "exchange": token_info["exchange"]
                    }
        except Exception as e:
            logger.warning(f"Error fetching Angel One LTP for {symbol}: {e}")
        return None

    @classmethod
    async def get_ltp(cls, symbol: str) -> Optional[Dict[str, Any]]:
        return cls.get_ltp_sync(symbol)

    @classmethod
    def get_candle_data_sync(
        cls,
        symbol: str,
        interval: str = "5m",
        days_back: int = 5
    ) -> Optional[Dict[str, Any]]:
        """
        Synchronously fetches historical OHLC candle data from Angel One SmartAPI.
        Translates to the standard technical analysis format.
        """
        token_info = cls.resolve_token(symbol)
        if not token_info:
            return None

        login_res = cls.login_sync()
        if not login_res.get("status"):
            return None

        angel_interval = INTERVAL_MAP.get(interval, "FIVE_MINUTE")
        now = datetime.datetime.now()
        from_date = now - datetime.timedelta(days=days_back)
        
        from_date_str = from_date.strftime("%Y-%m-%d 09:15")
        to_date_str = now.strftime("%Y-%m-%d %H:%M")

        url = f"{cls.BASE_URL}/rest/secure/angelbroking/historical/v1/getCandleData"
        payload = {
            "exchange": token_info["exchange"],
            "symboltoken": token_info["symboltoken"],
            "interval": angel_interval,
            "fromdate": from_date_str,
            "todate": to_date_str
        }

        try:
            with httpx.Client(timeout=8.0) as client:
                res = client.post(url, json=payload, headers=cls.get_headers(cls._session_token))
                data = res.json()
                if data.get("status") is True and data.get("data"):
                    raw_candles = data["data"]
                    valid_candles = []
                    for c in raw_candles:
                        dt_str = c[0]
                        try:
                            dt = datetime.datetime.fromisoformat(dt_str)
                            ts = int(dt.timestamp())
                        except Exception:
                            ts = int(time.time())

                        valid_candles.append({
                            "time": ts,
                            "open": round(float(c[1]), 2),
                            "high": round(float(c[2]), 2),
                            "low": round(float(c[3]), 2),
                            "close": round(float(c[4]), 2),
                            "volume": int(c[5]) if len(c) > 5 else 0
                        })

                    if not valid_candles:
                        return None

                    cmp = valid_candles[-1]["close"]
                    prev_close = valid_candles[-2]["close"] if len(valid_candles) > 1 else cmp
                    change = round(cmp - prev_close, 2)
                    change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0

                    return {
                        "symbol": symbol,
                        "source": "ANGEL_ONE",
                        "current_price": round(cmp, 2),
                        "previous_close": round(prev_close, 2),
                        "change": change,
                        "change_pct": change_pct,
                        "day_high": max(c["high"] for c in valid_candles[-75:]),
                        "day_low": min(c["low"] for c in valid_candles[-75:]),
                        "interval": interval,
                        "candles": valid_candles[-60:]
                    }
        except Exception as e:
            logger.warning(f"Error fetching Angel One candle data for {symbol}: {e}")
        return None

    @classmethod
    async def get_candle_data(
        cls,
        symbol: str,
        interval: str = "5m",
        days_back: int = 5
    ) -> Optional[Dict[str, Any]]:
        return cls.get_candle_data_sync(symbol, interval, days_back)

    @classmethod
    async def test_connection(cls) -> Dict[str, Any]:
        """Tests Angel One SmartAPI credentials and retrieves live Nifty 50 quote."""
        login_res = cls.login_sync(force=True)
        if not login_res.get("status"):
            return {
                "status": "error",
                "provider": "Angel One SmartAPI",
                "connected": False,
                "message": login_res.get("message", "Login failed")
            }

        ltp_data = cls.get_ltp_sync("NIFTY 50")
        if ltp_data:
            return {
                "status": "success",
                "provider": "Angel One SmartAPI",
                "connected": True,
                "message": f"Successfully connected to Angel One SmartAPI! Live NIFTY 50 LTP: ₹{ltp_data['ltp']:,.2f}",
                "sample_quote": ltp_data
            }
        else:
            return {
                "status": "success",
                "provider": "Angel One SmartAPI",
                "connected": True,
                "message": "Login succeeded! Token active. (Live tick will stream when market is open)."
            }

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        configured = cls.is_configured()
        active = bool(cls._session_token and time.time() < cls._token_expiry)
        return {
            "provider": "Angel One SmartAPI",
            "is_free": True,
            "configured": configured,
            "active": active,
            "client_code": cls._client_code or getattr(settings, "ANGEL_ONE_CLIENT_CODE", ""),
            "message": "Connected to Angel One SmartAPI live feed" if active else (
                "Configured (will authenticate on first request)" if configured else "Not configured. Enter API Key & TOTP in Settings."
            )
        }
