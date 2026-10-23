import json, datetime as dt
import xml.etree.ElementTree as ET
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

NIFTY = ("RELIANCE TCS HDFCBANK ICICIBANK INFY BHARTIARTL ITC SBIN LT HINDUNILVR KOTAKBANK AXISBANK "
         "BAJFINANCE MARUTI SUNPHARMA TITAN ONGC NTPC POWERGRID ULTRACEMCO ASIANPAINT WIPRO HCLTECH M&M "
         "TATAMOTORS TATASTEEL JSWSTEEL ADANIENT ADANIPORTS COALINDIA BAJAJFINSV NESTLEIND TECHM GRASIM "
         "HINDALCO DRREDDY CIPLA EICHERMOT BPCL APOLLOHOSP BRITANNIA HEROMOTOCO INDUSINDBK SBILIFE "
         "HDFCLIFE TRENT BEL SHRIRAMFIN HAL BAJAJ-AUTO").split()

def movers():
    syms = [s + ".NS" for s in NIFTY]
    try:
        df = yf.download(syms, period="7d", interval="1d", group_by="ticker",
                         progress=False, auto_adjust=True, threads=True)
    except Exception as e:
        print("movers fail", e); return {"gainers": [], "losers": []}
    rows = []
    for s in syms:
        try:
            c = df[s]["Close"].dropna()
            if len(c) < 2: continue
            rows.append({"name": s[:-3], "price": round(float(c.iloc[-1]), 2),
                         "chg": round((float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100, 2)})
        except Exception:
            continue
    rows.sort(key=lambda r: r["chg"], reverse=True)
    return {"gainers": rows[:5], "losers": rows[-5:][::-1]}

FEEDS = [("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
         ("Google News", "https://news.google.com/rss/search?q=stock+market+India+when:1d&hl=en-IN&gl=IN&ceid=IN:en"),
         ("Google News Hindi", "https://news.google.com/rss/search?q=शेयर+बाजार+when:1d&hl=hi&gl=IN&ceid=IN:hi")]

def news():
    out, seen = [], set()
    for src, url in FEEDS:
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            root = ET.fromstring(r.content)
            n = 0
            for it in root.iter("item"):
                t = (it.findtext("title") or "").strip()
                l = (it.findtext("link") or "").strip()
                if not t or t in seen: continue
                seen.add(t)
                out.append({"title": t, "link": l, "src": src, "time": it.findtext("pubDate") or ""})
                n += 1
                if n >= 7: break
        except Exception as e:
            print("news fail", src, e)
    return out

data = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(), "assets": [], "watch": [], "fii": fii_dii(),
        "movers": movers(), "news": news()}
for n, s in ASSETS.items():
    a = get(s)
    if a: data["assets"].append({"name": n, **a})
for n, s in WATCH.items():
    a = get(s)
    if a: data["watch"].append({"name": n, **a})
json.dump(data, open("data.json", "w"), ensure_ascii=False)
print("saved", len(data["assets"]), "assets", len(data["watch"]), "stocks")
