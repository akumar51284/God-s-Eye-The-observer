import json, datetime as dt
import pandas as pd, requests, yfinance as yf

ASSETS = {"NIFTY":"^NSEI","SENSEX":"^BSESN","BANKNIFTY":"^NSEBANK","GOLD":"GC=F",
          "SILVER":"SI=F","CRUDEOIL":"CL=F","BITCOIN":"BTC-USD","NASDAQ":"^IXIC"}
WATCH = {"RELIANCE":"RELIANCE.NS","TCS":"TCS.NS","HDFCBANK":"HDFCBANK.NS",
         "INFY":"INFY.NS","HAL":"HAL.NS"}   # apne stocks yahan badlo

clip = lambda v, a, b: max(a, min(b, v))

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)

def analyse(close):
    close = close.dropna()
    if len(close) < 55: return None
    last = float(close.iloc[-1])
    r = float(rsi(close).iloc[-1])
    s20 = float(close.rolling(20).mean().iloc[-1])
    s50 = float(close.rolling(50).mean().iloc[-1])
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    hist = float((macd - macd.ewm(span=9, adjust=False).mean()).iloc[-1])
    chg = (last / float(close.iloc[-2]) - 1) * 100
    # score: -10 se +10
    score = (clip((r - 50) / 5, -3, 3) + (2 if last > s20 else -2)
             + (2 if last > s50 else -2) + (2 if hist > 0 else -2) + clip(chg, -1, 1))
    dma = ("20 aur 50 DMA ke upar" if last > s20 and last > s50 else
           "20 aur 50 DMA ke neeche" if last < s20 and last < s50 else
           "20 DMA ke upar, 50 ke neeche" if last > s20 else "50 DMA ke upar, 20 ke neeche")
    return {"price": round(last, 2), "chg": round(chg, 2), "score": round(score, 1),
            "rsi": round(r, 1), "dma": dma, "macd": "Bullish" if hist > 0 else "Bearish",
            "spark": [round(float(x), 2) for x in close.tail(30)]}

def get(sym):
    try:
        return analyse(yf.Ticker(sym).history(period="6mo", interval="1d")["Close"])
    except Exception as e:
        print("fail", sym, e); return None

def fii_dii():
    try:
        s = requests.Session()
        h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://www.nseindia.com/"}
        s.get("https://www.nseindia.com", headers=h, timeout=15)
        rows = s.get("https://www.nseindia.com/api/fiidiiTradeReact", headers=h, timeout=15).json()
        out = {}
        for r in rows:
            k = "fii" if "FII" in r["category"] else "dii"
            out.setdefault(r["date"], {})[k] = float(r["netValue"])
        return [{"date": d, **v} for d, v in out.items()]
    except Exception as e:
        print("fii/dii fail", e); return []

data = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(), "assets": [], "watch": [], "fii": fii_dii()}
for n, s in ASSETS.items():
    a = get(s)
    if a: data["assets"].append({"name": n, **a})
for n, s in WATCH.items():
    a = get(s)
    if a: data["watch"].append({"name": n, **a})
json.dump(data, open("data.json", "w"), ensure_ascii=False)
print("saved", len(data["assets"]), "assets", len(data["watch"]), "stocks")
