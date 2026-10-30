import time
import struct
import hmac
import hashlib
import base64
import logging
import datetime
import threading
import re
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
    _scrip_cache: Dict[str, Any] = {}
    _scrip_cache_time: Dict[str, float] = {}
    _candle_cache: Dict[str, Any] = {}
    _login_lock = threading.Lock()
    _candle_lock = threading.Lock()

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
            "X-ClientPublicIP": "49.248.4.74",
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

        with cls._login_lock:
            # Double-check inside lock
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
        Synchronously fetches historical OHLC candle data from Angel One SmartAPI
        with 30-second memory cache and real-time live LTP tick injection.
        """
        token_info = cls.resolve_token(symbol)
        if not token_info:
            return None

        cache_key = f"{token_info['exchange']}_{token_info['symboltoken']}_{interval}"
        now_ts = time.time()

        # Check in-memory candle cache (valid for 30s)
        cached = cls._candle_cache.get(cache_key)
        result_candles = None
        if cached and (now_ts - cached.get("time", 0)) < 30:
            result_candles = dict(cached["data"])

        if not result_candles:
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
                with cls._candle_lock:
                    with httpx.Client(timeout=8.0) as client:
                        res = client.post(url, json=payload, headers=cls.get_headers(cls._session_token))
                        # If rate limited (403/429), back off 0.35s and retry once
                        if res.status_code in (403, 429):
                            time.sleep(0.35)
                            res = client.post(url, json=payload, headers=cls.get_headers(cls._session_token))

                        if res.status_code == 200 and res.content:
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

                                if valid_candles:
                                    cmp = valid_candles[-1]["close"]
                                    prev_close = valid_candles[-2]["close"] if len(valid_candles) > 1 else cmp
                                    change = round(cmp - prev_close, 2)
                                    change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0

                                    result_candles = {
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
                                    cls._candle_cache[cache_key] = {"time": now_ts, "data": result_candles}
            except Exception as e:
                logger.warning(f"Error fetching Angel One candle data for {symbol}: {e}")

        # Inject real-time live LTP directly into the result so prices are NEVER delayed
        if result_candles:
            try:
                ltp_data = cls.get_ltp_sync(symbol)
                if ltp_data and ltp_data.get("ltp") and ltp_data["ltp"] > 0:
                    live_ltp = round(float(ltp_data["ltp"]), 2)
                    result_candles["current_price"] = live_ltp
                    prev_c = result_candles.get("previous_close", live_ltp)
                    result_candles["change"] = round(live_ltp - prev_c, 2)
                    result_candles["change_pct"] = round(((live_ltp - prev_c) / prev_c) * 100, 2) if prev_c else 0.0
                    if result_candles.get("candles"):
                        last_c = result_candles["candles"][-1]
                        last_c["close"] = live_ltp
                        last_c["high"] = max(last_c["high"], live_ltp)
                        last_c["low"] = min(last_c["low"], live_ltp)
            except Exception as e:
                logger.warning(f"Could not inject live LTP for {symbol}: {e}")

            return result_candles

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

    @classmethod
    def _parse_tradingsymbol_date(cls, ts: str) -> Optional[datetime.date]:
        """
        Extracts expiry date from any NSE or BSE derivative trading symbol:
        1. BSE Weekly: SENSEX26N0574400PE -> 2026-11-05
        2. BSE Monthly: SENSEX26NOV74400PE -> 2026-11-26
        3. NSE Weekly/Monthly: NIFTY03NOV2623100CE -> 2026-11-03
        """
        if not ts:
            return None
        # 1. BSE Weekly format: SENSEX26N05... (YYMDD)
        m_bse_w = re.search(r"SENSEX([0-9]{2})([1-9OND])([0-9]{2})", ts)
        if m_bse_w:
            bse_month_map = {'1':1,'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'O':10,'N':11,'D':12}
            try:
                yy, m_c, dd = m_bse_w.groups()
                return datetime.date(2000 + int(yy), bse_month_map[m_c], int(dd))
            except Exception:
                pass

        # 2. BSE Monthly format: SENSEX26NOV74400... (YYMMM)
        m_bse_m = re.search(r"SENSEX([0-9]{2})([A-Z]{3})[0-9]{5}", ts)
        if m_bse_m:
            try:
                yy, m_s = m_bse_m.groups()
                return datetime.datetime.strptime(f"26{m_s}{yy}", "%d%b%y").date()
            except Exception:
                pass

        # 3. NSE Weekly/Monthly format: DDMMMYY (e.g. 03NOV26)
        m_nse = re.search(r"([0-9]{2}[A-Z]{3}(?:26|27|28|29))", ts)
        if m_nse:
            try:
                return datetime.datetime.strptime(m_nse.group(1), "%d%b%y").date()
            except Exception:
                pass

        return None

    @classmethod
    def get_real_expiries_sync(cls, underlying: str) -> List[Dict[str, Any]]:
        """
        Fetches the official exchange derivative expiry dates directly from Angel One
        SmartAPI searchScrip master, ensuring 100% alignment with the broker's option chain.
        """
        if not cls.is_configured():
            return []

        login_res = cls.login_sync()
        if not login_res.get("status"):
            return []

        underlying_clean = underlying.upper().strip()
        is_sensex = "SENSEX" in underlying_clean
        is_banknifty = "BANK" in underlying_clean
        is_finnifty = "FIN" in underlying_clean
        is_midcp = "MID" in underlying_clean
        exchange = "BFO" if is_sensex else "NFO"

        if is_sensex:
            base_keyword = "SENSEX"
        elif is_banknifty:
            base_keyword = "BANKNIFTY"
        elif is_finnifty:
            base_keyword = "FINNIFTY"
        elif is_midcp:
            base_keyword = "MIDCPNIFTY"
        else:
            base_keyword = "NIFTY"

        cache_key = f"{exchange}_{base_keyword}"
        now = time.time()

        if cache_key not in cls._scrip_cache or (now - cls._scrip_cache_time.get(cache_key, 0) > 900):
            try:
                url = f"{cls.BASE_URL}/rest/secure/angelbroking/order/v1/searchScrip"
                headers = cls.get_headers(cls._session_token)
                with httpx.Client(timeout=8.0) as client:
                    res = client.post(url, json={"exchange": exchange, "searchscrip": base_keyword}, headers=headers)
                    if res.status_code == 200:
                        data = res.json().get("data", [])
                        if data:
                            cls._scrip_cache[cache_key] = data
                            cls._scrip_cache_time[cache_key] = now
            except Exception as e:
                logger.warning(f"Error fetching Angel One scrip master for {cache_key}: {e}")

        scrips = cls._scrip_cache.get(cache_key, [])
        if not scrips:
            return []

        today = datetime.date.today()
        dates_found = set()
        for item in scrips:
            exp = item.get("expiry")
            d = None
            if exp:
                for fmt in ("%d%b%y", "%d%b%Y", "%d-%b-%Y", "%d %b %Y", "%Y-%m-%d"):
                    try:
                        d = datetime.datetime.strptime(exp.strip(), fmt).date()
                        break
                    except Exception:
                        pass
            if not d:
                d = cls._parse_tradingsymbol_date(item.get("tradingsymbol", ""))

            if d and d >= today and d.year <= today.year + 1:
                dates_found.add(d)

        parsed_expiries = []
        for dt in sorted(list(dates_found)):
            dte = (dt - today).days
            formatted_date = dt.strftime("%d %b %Y")
            next_wk = dt + datetime.timedelta(days=7)
            is_monthly = (next_wk.month != dt.month)
            tag = "0DTE" if dte == 0 else ("Monthly" if is_monthly else "Weekly")
            parsed_expiries.append({
                "id": formatted_date,
                "date": formatted_date,
                "raw_expiry": formatted_date,
                "label": f"{dt.strftime('%d %b')} ({'Today / 0DTE' if dte == 0 else tag})",
                "tag": tag,
                "dte": dte
            })

        parsed_expiries.sort(key=lambda x: x["dte"])
        return parsed_expiries

    @classmethod
    def get_option_quote_sync(
        cls,
        underlying: str,
        expiry_str: str,
        strike: int,
        option_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves real-time live Option LTP and market quote from Angel One SmartAPI
        for any strike, expiry, and option type (CE/PE) on BFO (SENSEX) or NFO (NIFTY/BANKNIFTY).
        """
        if not cls.is_configured():
            return None

        login_res = cls.login_sync()
        if not login_res.get("status"):
            return None

        underlying_clean = underlying.upper().strip()
        is_sensex = "SENSEX" in underlying_clean
        is_banknifty = "BANK" in underlying_clean
        is_finnifty = "FIN" in underlying_clean
        is_midcp = "MID" in underlying_clean
        exchange = "BFO" if is_sensex else "NFO"

        if is_sensex:
            base_keyword = "SENSEX"
        elif is_banknifty:
            base_keyword = "BANKNIFTY"
        elif is_finnifty:
            base_keyword = "FINNIFTY"
        elif is_midcp:
            base_keyword = "MIDCPNIFTY"
        else:
            base_keyword = "NIFTY"

        cache_key = f"{exchange}_{base_keyword}"
        now = time.time()

        # Check scrip cache (refresh every 15 minutes)
        if cache_key not in cls._scrip_cache or (now - cls._scrip_cache_time.get(cache_key, 0) > 900):
            try:
                url = f"{cls.BASE_URL}/rest/secure/angelbroking/order/v1/searchScrip"
                headers = cls.get_headers(cls._session_token)
                with httpx.Client(timeout=8.0) as client:
                    res = client.post(url, json={"exchange": exchange, "searchscrip": base_keyword}, headers=headers)
                    if res.status_code == 200:
                        data = res.json().get("data", [])
                        if data:
                            cls._scrip_cache[cache_key] = data
                            cls._scrip_cache_time[cache_key] = now
            except Exception as e:
                logger.warning(f"Error fetching Angel One scrip master for {cache_key}: {e}")

        scrips = cls._scrip_cache.get(cache_key, [])
        if not scrips:
            return None

        # Parse expiry date
        dt = None
        for fmt in ("%d %b %Y", "%Y-%m-%d", "%d-%b-%Y", "%d %B %Y"):
            try:
                dt = datetime.datetime.strptime(expiry_str.strip(), fmt)
                break
            except Exception:
                continue

        if not dt:
            dt = datetime.datetime.now()

        y2 = dt.strftime("%y")
        m3 = dt.strftime("%b").upper()
        m1 = m3[0]
        d2 = dt.strftime("%d")

        opt = option_type.upper().strip()
        stk = str(int(strike))

        # Build probable tradingsymbol patterns used by BSE and NSE
        patterns = [
            f"{base_keyword}{y2}{m1}{d2}{stk}{opt}",   # BSE weekly (e.g. SENSEX26O2273400CE)
            f"{base_keyword}{y2}{m3}{stk}{opt}",       # BSE/NSE monthly (e.g. SENSEX26OCT73400CE)
            f"{base_keyword}{d2}{m3}{y2}{stk}{opt}",   # NSE weekly/monthly (e.g. NIFTY22OCT26...)
            f"{base_keyword}{y2}{m3}{d2}{stk}{opt}",
            f"{base_keyword}{y2}{d2}{m3}{stk}{opt}",
        ]

        matched = None
        # 1. Exact pattern match
        for item in scrips:
            ts = item.get("tradingsymbol", "")
            if ts in patterns:
                matched = item
                break

        # 2. Fuzzy suffix match by strike + opt + date components
        if not matched:
            suffix = f"{stk}{opt}"
            candidates = [x for x in scrips if x.get("tradingsymbol", "").endswith(suffix)]
            for cand in candidates:
                ts = cand.get("tradingsymbol", "")
                if (f"{y2}{m1}{d2}" in ts) or (f"{d2}{m3}{y2}" in ts) or (f"{y2}{m3}" in ts) or (f"{m3}{y2}" in ts):
                    matched = cand
                    break

            # 3. Fallback: take the candidate matching the strike and option type with closest upcoming date
            if not matched and candidates:
                def parse_cand_date(cand):
                    d = cls._parse_tradingsymbol_date(cand.get("tradingsymbol", ""))
                    return d if d else datetime.date(2099, 1, 1)

                target_d = dt.date()
                upcoming = [c for c in candidates if parse_cand_date(c) >= target_d]
                if upcoming:
                    upcoming.sort(key=lambda c: parse_cand_date(c))
                    matched = upcoming[0]
                else:
                    candidates.sort(key=lambda c: abs((parse_cand_date(c) - target_d).days))
                    matched = candidates[0]

        if not matched:
            return None

        # Fetch live quote for the matched contract using official market quote endpoint
        try:
            quote_url = f"{cls.BASE_URL}/rest/secure/angelbroking/market/v1/quote/"
            headers = cls.get_headers(cls._session_token)
            with httpx.Client(timeout=6.0) as client:
                res = client.post(
                    quote_url,
                    json={
                        "mode": "FULL",
                        "exchangeTokens": {
                            exchange: [str(matched["symboltoken"])]
                        }
                    },
                    headers=headers
                )
                if res.status_code == 200:
                    data = res.json().get("data", {})
                    fetched = data.get("fetched", [])
                    if fetched:
                        item = fetched[0]
                        ltp_val = float(item.get("ltp", 0.0) or 0.0)
                        close_val = float(item.get("close", 0.0) or 0.0)
                        open_val = float(item.get("open", 0.0) or 0.0)
                        high_val = float(item.get("high", 0.0) or 0.0)
                        low_val = float(item.get("low", 0.0) or 0.0)
                        effective_ltp = ltp_val if ltp_val > 0 else (close_val if close_val > 0 else high_val)

                        return {
                            "tradingsymbol": matched["tradingsymbol"],
                            "symboltoken": matched["symboltoken"],
                            "exchange": exchange,
                            "ltp": round(effective_ltp, 2),
                            "close": round(close_val, 2),
                            "open": round(open_val, 2),
                            "high": round(high_val, 2),
                            "low": round(low_val, 2),
                            "strike": strike,
                            "option_type": opt,
                            "is_live_angel_one": True
                        }
        except Exception as e:
            logger.warning(f"Error fetching Angel One market quote for {matched.get('tradingsymbol')}: {e}")

        return None

    @classmethod
    def get_batch_ltp_sync(
        cls,
        tokens_by_exchange: Dict[str, List[str]]
    ) -> Dict[str, float]:
        """
        Fetches live tick LTP in ONE single API call for all tokens across NFO & BFO
        using Angel One's official Market Quote API:
        POST /rest/secure/angelbroking/market/v1/quote/
        """
        if not cls.is_configured():
            return {}

        login_res = cls.login_sync()
        if not login_res.get("status"):
            return {}

        url = f"{cls.BASE_URL}/rest/secure/angelbroking/market/v1/quote/"
        headers = cls.get_headers(cls._session_token)

        clean_tokens = {}
        for ex, toks in tokens_by_exchange.items():
            valid_toks = [str(t) for t in toks if t]
            if valid_toks:
                clean_tokens[ex] = list(set(valid_toks))

        if not clean_tokens:
            return {}

        ltp_map = {}
        try:
            with httpx.Client(timeout=6.0) as client:
                res = client.post(
                    url,
                    json={
                        "mode": "LTP",
                        "exchangeTokens": clean_tokens
                    },
                    headers=headers
                )
                if res.status_code == 200:
                    data = res.json().get("data", {})
                    fetched = data.get("fetched", [])
                    for item in fetched:
                        tok = str(item.get("symbolToken", ""))
                        ltp = float(item.get("ltp", 0.0) or 0.0)
                        if tok and ltp > 0:
                            ltp_map[tok] = round(ltp, 2)
                            ts = item.get("tradingSymbol", "")
                            if ts:
                                ltp_map[ts] = round(ltp, 2)
        except Exception as e:
            logger.warning(f"Error fetching Angel One batch market quote: {e}")

        return ltp_map

    @classmethod
    def get_contract_ltp_sync(
        cls,
        exchange: Optional[str] = "NFO",
        tradingsymbol: Optional[str] = None,
        symboltoken: Optional[str] = None
    ) -> Optional[float]:
        """
        Directly fetches live tick LTP for any derivative contract token from Angel One.
        """
        if not symboltoken or not cls.is_configured():
            return None

        login_res = cls.login_sync()
        if not login_res.get("status"):
            return None

        ex = exchange or "NFO"
        tok = str(symboltoken)
        batch_res = cls.get_batch_ltp_sync({ex: [tok]})
        return batch_res.get(tok)

    @classmethod
    def fetch_option_contract_ltp(
        cls,
        base_keyword: str,
        strike: float,
        option_type: str,
        expiry_str: str,
        exchange: str = "NFO"
    ) -> Optional[Dict[str, Any]]:
        """
        Convenience wrapper around get_option_quote_sync.
        """
        return cls.get_option_quote_sync(
            underlying=base_keyword,
            expiry_str=expiry_str,
            strike=int(strike),
            option_type=option_type
        )

    @classmethod
    def get_profile(cls) -> Dict[str, Any]:
        """Fetch client profile from Angel One SmartAPI."""
        login_res = cls.login_sync()
        if not login_res.get("status"):
            return {"status": False, "message": login_res.get("message", "Not logged in")}
        token = login_res.get("token")
        try:
            url = f"{cls.BASE_URL}/rest/secure/angelbroking/user/v1/getProfile"
            headers = cls.get_headers(token)
            with httpx.Client(timeout=6.0) as client:
                res = client.get(url, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    return data
        except Exception as e:
            logger.warning(f"Error fetching Angel One profile: {e}")
            return {"status": False, "message": str(e)}
        return {"status": False, "message": "Failed to fetch profile"}

    @classmethod
    def get_rms(cls) -> Dict[str, Any]:
        """Fetch RMS / Funds and Margin details from Angel One SmartAPI."""
        login_res = cls.login_sync()
        if not login_res.get("status"):
            return {"status": False, "message": login_res.get("message", "Not logged in")}
        token = login_res.get("token")
        try:
            url = f"{cls.BASE_URL}/rest/secure/angelbroking/user/v1/getRMS"
            headers = cls.get_headers(token)
            with httpx.Client(timeout=6.0) as client:
                res = client.get(url, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    return data
        except Exception as e:
            logger.warning(f"Error fetching Angel One RMS: {e}")
            return {"status": False, "message": str(e)}
        return {"status": False, "message": "Failed to fetch RMS funds"}

    @classmethod
    def place_order(
        cls,
        tradingsymbol: str,
        symboltoken: str,
        exchange: str,
        transactiontype: str,
        quantity: int,
        price: float = 0.0,
        ordertype: str = "MARKET",
        producttype: str = "INTRADAY"
    ) -> Dict[str, Any]:
        """Place live order via Angel One SmartAPI."""
        login_res = cls.login_sync()
        if not login_res.get("status"):
            return {"status": False, "message": login_res.get("message", "Not logged in")}
        token = login_res.get("token")
        try:
            url = f"{cls.BASE_URL}/rest/secure/angelbroking/order/v1/placeOrder"
            headers = cls.get_headers(token)
            payload = {
                "variety": "NORMAL",
                "tradingsymbol": tradingsymbol,
                "symboltoken": symboltoken,
                "transactiontype": transactiontype.upper(),
                "exchange": exchange,
                "ordertype": ordertype.upper(),
                "producttype": producttype.upper(),
                "duration": "DAY",
                "price": str(price) if ordertype.upper() != "MARKET" else "0",
                "squareoff": "0",
                "stoploss": "0",
                "quantity": str(quantity)
            }
            with httpx.Client(timeout=8.0) as client:
                res = client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    return res.json()
                return {"status": False, "message": f"HTTP {res.status_code}: {res.text}"}
        except Exception as e:
            logger.warning(f"Error placing Angel One order: {e}")
            return {"status": False, "message": str(e)}


