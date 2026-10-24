import json, io, math, re, datetime as dt
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus
import pandas as pd, requests, yfinance as yf

ASSETS = {"NIFTY":"^NSEI","SENSEX":"^BSESN","BANKNIFTY":"^NSEBANK","GOLD":"GC=F",
          "SILVER":"SI=F","CRUDEOIL":"CL=F","NASDAQ":"^IXIC"}
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
         "TATASTEEL JSWSTEEL ADANIENT ADANIPORTS COALINDIA BAJAJFINSV NESTLEIND TECHM GRASIM "
         "HINDALCO DRREDDY CIPLA EICHERMOT BPCL APOLLOHOSP BRITANNIA HEROMOTOCO INDUSINDBK SBILIFE "
         "HDFCLIFE TRENT BEL SHRIRAMFIN HAL BAJAJ-AUTO").split()

# sector: (index symbol, top 5 stocks) - weights approx, apne hisaab se badal sakte ho
SECTORS = {
 "NIFTY BANK": ("^NSEBANK", "HDFCBANK ICICIBANK SBIN KOTAKBANK AXISBANK"),
 "NIFTY IT": ("^CNXIT", "TCS INFY HCLTECH WIPRO TECHM"),
 "NIFTY FMCG": ("^CNXFMCG", "ITC HINDUNILVR NESTLEIND BRITANNIA TATACONSUM"),
 "NIFTY AUTO": ("^CNXAUTO", "M&M MARUTI BAJAJ-AUTO EICHERMOT HEROMOTOCO"),
 "NIFTY PHARMA": ("^CNXPHARMA", "SUNPHARMA CIPLA DRREDDY LUPIN DIVISLAB"),
 "NIFTY METAL": ("^CNXMETAL", "TATASTEEL JSWSTEEL HINDALCO VEDL JINDALSTEL"),
 "NIFTY ENERGY": ("^CNXENERGY", "RELIANCE ONGC NTPC POWERGRID COALINDIA"),
 "NIFTY REALTY": ("^CNXREALTY", "DLF GODREJPROP LODHA OBEROIRLTY PHOENIXLTD"),
 "FIN SERVICE": ("NIFTY_FIN_SERVICE.NS", "BAJFINANCE BAJAJFINSV SHRIRAMFIN SBILIFE HDFCLIFE"),
}

def bulk(syms):
    syms = sorted(set(syms))
    try:
        df = yf.download(syms, period="6mo", interval="1d", group_by="ticker",
                         progress=False, auto_adjust=True, threads=True)
    except Exception as e:
        print("bulk fail", e); return {}
    out = {}
    for s in syms:
        try:
            a = analyse(df[s]["Close"])
            if a: out[s] = a
        except Exception:
            continue
    return out

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

UA = {"User-Agent": "Mozilla/5.0"}
# GIFT Nifty ka koi pakka free Yahoo symbol nahi mila. Mil jaye to yahan likh do (jaise "XYZ.NS")
GIFT_SYMBOL = ""

def n500():
    try:
        r = requests.get("https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv", headers=UA, timeout=20)
        syms = [str(s).strip() for s in pd.read_csv(io.StringIO(r.text))["Symbol"] if str(s).strip()]
        if len(syms) > 300: return syms
    except Exception as e:
        print("nifty500 list fail", e)
    return NIFTY

def ohl_scan():
    syms = n500(); src = "nifty500" if len(syms) > 300 else "nifty50"
    full = [s + ".NS" for s in syms]; rows = []
    for i in range(0, len(full), 100):
        part = full[i:i + 100]
        try:
            df = yf.download(part, period="5d", interval="1d", group_by="ticker",
                             progress=False, auto_adjust=False, threads=True)
        except Exception as e:
            print("ohl fail", e); continue
        for s in part:
            try:
                d = df[s][["Open", "High", "Low", "Close"]].dropna()
                if len(d) < 2: continue
                o, h, l, c = [float(x) for x in d.iloc[-1]]; pc = float(d["Close"].iloc[-2])
                rows.append({"name": s[:-3], "open": round(o, 2), "high": round(h, 2), "low": round(l, 2),
                             "price": round(c, 2), "chg": round((c / pc - 1) * 100, 2)})
            except Exception:
                continue
    tol = 0.0003
    low = [r for r in rows if r["open"] > 0 and r["high"] > r["low"] and (r["open"] - r["low"]) / r["open"] <= tol]
    high = [r for r in rows if r["open"] > 0 and r["high"] > r["low"] and (r["high"] - r["open"]) / r["open"] <= tol]
    low.sort(key=lambda r: r["chg"], reverse=True); high.sort(key=lambda r: r["chg"])
    return {"src": src, "scanned": len(rows), "low": low[:40], "high": high[:40]}

GLOBAL = [("S&P 500", "^GSPC"), ("Dow Jones", "^DJI"), ("Nasdaq", "^IXIC"), ("Nikkei 225", "^N225"),
          ("Hang Seng", "^HSI"), ("Crude WTI", "CL=F"), ("Brent", "BZ=F"), ("USD/INR", "USDINR=X"),
          ("Dollar Index", "DX-Y.NYB"), ("US 10Y Yield", "^TNX"), ("US VIX", "^VIX")]

def quote(sym):
    try:
        c = yf.Ticker(sym).history(period="10d", interval="1d")["Close"].dropna()
        if len(c) < 2: return None
        return {"price": round(float(c.iloc[-1]), 2), "chg": round((float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100, 2)}
    except Exception as e:
        print("quote fail", sym, e); return None

def global_cues():
    items = []
    for n, s in GLOBAL:
        q = quote(s)
        if q: items.append({"name": n, **q})
    idx = [i["chg"] for i in items if i["name"] in ("S&P 500", "Dow Jones", "Nasdaq", "Nikkei 225", "Hang Seng")]
    avg = sum(idx) / len(idx) if idx else 0
    return {"mood": "Positive" if avg > 0.3 else "Negative" if avg < -0.3 else "Mixed", "items": items}

def day_range():
    n = quote("^NSEI"); v = quote("^INDIAVIX")
    if not n or not v: return None
    pct = v["price"] / math.sqrt(252); pts = n["price"] * pct / 100
    return {"vix": v["price"], "close": n["price"], "pts": round(pts, 1), "pct": round(pct, 2),
            "low": round(n["price"] - pts, 1), "high": round(n["price"] + pts, 1)}

NAMES = {"M&M": "Mahindra and Mahindra", "LT": "Larsen and Toubro", "BEL": "Bharat Electronics", "HAL": "Hindustan Aeronautics",
 "ITC": "ITC Ltd", "SBIN": "SBI", "TITAN": "Titan Company", "TRENT": "Trent Tata", "GRASIM": "Grasim Industries",
 "HEROMOTOCO": "Hero MotoCorp", "BAJAJ-AUTO": "Bajaj Auto", "HDFCLIFE": "HDFC Life", "SBILIFE": "SBI Life",
 "TECHM": "Tech Mahindra", "NESTLEIND": "Nestle India", "ASIANPAINT": "Asian Paints", "ULTRACEMCO": "UltraTech Cement",
 "COALINDIA": "Coal India", "POWERGRID": "Power Grid", "ADANIENT": "Adani Enterprises", "ADANIPORTS": "Adani Ports",
 "APOLLOHOSP": "Apollo Hospitals", "BAJFINANCE": "Bajaj Finance", "BAJAJFINSV": "Bajaj Finserv", "BHARTIARTL": "Bharti Airtel",
 "DRREDDY": "Dr Reddys", "EICHERMOT": "Eicher Motors", "HINDUNILVR": "Hindustan Unilever", "INDUSINDBK": "IndusInd Bank",
 "JSWSTEEL": "JSW Steel", "KOTAKBANK": "Kotak Mahindra Bank", "SUNPHARMA": "Sun Pharma", "SHRIRAMFIN": "Shriram Finance",
 "TATASTEEL": "Tata Steel", "MARUTI": "Maruti Suzuki", "HDFCBANK": "HDFC Bank", "ICICIBANK": "ICICI Bank", "AXISBANK": "Axis Bank",
 "RELIANCE": "Reliance Industries", "INFY": "Infosys", "HCLTECH": "HCL Tech", "BRITANNIA": "Britannia Industries"}
POS = re.compile(r"\b(?:surge|surges|surged|rally|rallies|rallied|jump|jumps|jumped|gain|gains|gained|soar|soars|soared|"
 r"upgrade|upgrades|upgraded|outperform|beats|beat|strong|bullish|wins|bags|boost|boosts|positive|recovery|recovers|"
 r"rise|rises|rose|climbs|climb|buy|record high|profit up|profit jumps|profit rises|profit grew|top pick)\b")
NEG = re.compile(r"\b(?:fall|falls|fell|drop|drops|dropped|plunge|plunges|plunged|slump|slumps|crash|crashes|downgrade|"
 r"downgrades|downgraded|sell|selloff|loss|losses|weak|bearish|probe|fraud|penalty|fined|ban|banned|miss|misses|missed|"
 r"cut|cuts|decline|declines|declined|tumble|tumbles|slip|slips|resigns|raid|default|slide|slides|sink|sinks|lower|warns|warning|concern|concerns)\b")
senti = lambda t: len(POS.findall(t.lower())) - len(NEG.findall(t.lower()))

def stock_news(sym):
    url = "https://news.google.com/rss/search?q=" + quote_plus(NAMES.get(sym, sym) + " share NSE when:1d") + "&hl=en-IN&gl=IN&ceid=IN:en"
    out = []
    try:
        root = ET.fromstring(requests.get(url, headers=UA, timeout=15).content)
        for it in list(root.iter("item"))[:8]:
            t = (it.findtext("title") or "").strip()
            title, _, src = t.rpartition(" - ")
            if not title: title, src = t, ""
            out.append({"title": title, "src": src, "link": it.findtext("link") or "", "time": it.findtext("pubDate") or "", "h": senti(title)})
    except Exception as e:
        print("fno news fail", sym, e)
    return sym, out

def fno_watch():
    with ThreadPoolExecutor(8) as ex: res = list(ex.map(stock_news, NIFTY))
    total = sum(len(o) for _, o in res); rows = []; scores = {}
    for sym, o in res:
        if not o: continue
        s = max(-10, min(10, sum(x["h"] for x in o) * 2.5)); scores[sym] = s
        if s != 0:
            b = max(o, key=lambda x: abs(x["h"]))
            rows.append({"name": sym, "score": round(s, 1), "title": b["title"], "src": b["src"], "link": b["link"], "time": b["time"]})
    rows.sort(key=lambda r: abs(r["score"]), reverse=True)
    secs = []
    for name, (idx, lst) in SECTORS.items():
        v = [scores[x] for x in lst.split() if x in scores]
        if v: secs.append({"name": name, "score": round(sum(v) / len(v), 1)})
    return {"headlines": total, "stocks": len(res), "notable": len(rows), "rows": rows[:25], "sectors": secs}

nse = lambda n: n + ".NS"
R = bulk([nse(n) for n in NIFTY] + [nse(n) for _, l in SECTORS.values() for n in l.split()]
         + [i for i, _ in SECTORS.values()])

def row(n):
    a = R.get(nse(n))
    return {"name": n, "price": a["price"], "chg": a["chg"], "score": a["score"]} if a else None

stocks = [r for r in map(row, NIFTY) if r]
by_chg = sorted(stocks, key=lambda r: r["chg"], reverse=True)
sectors = []
for name, (idx, lst) in SECTORS.items():
    a = R.get(idx)
    if not a: print("sector skip", name); continue
    sectors.append({"name": name, "price": a["price"], "chg": a["chg"], "score": a["score"],
                    "spark": a["spark"], "stocks": [r for r in map(row, lst.split()) if r]})

data = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(), "assets": [], "watch": [],
        "fii": fii_dii(), "movers": {"gainers": by_chg[:5], "losers": by_chg[-5:][::-1]},
        "stocks": stocks, "sectors": sectors, "news": news()}
for n, s in ASSETS.items():
    a = get(s)
    if a: data["assets"].append({"name": n, **a})
for n, s in WATCH.items():
    a = get(s)
    if a: data["watch"].append({"name": n, **a})
g = get(GIFT_SYMBOL) if GIFT_SYMBOL else None
data["assets"].insert(1, {"name": "GIFT NIFTY", **g} if g else {"name": "GIFT NIFTY", "na": True})
data["ohl"] = ohl_scan(); data["global"] = global_cues(); data["range"] = day_range(); data["fno"] = fno_watch()
json.dump(data, open("data.json", "w"), ensure_ascii=False)
print("saved", len(data["assets"]), "assets", len(stocks), "stocks", len(sectors), "sectors")
