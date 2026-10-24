import json, io, math, re, datetime as dt
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus
import pandas as pd, requests, yfinance as yf

ASSETS = {"NIFTY":"^NSEI","SENSEX":"^BSESN","BANKNIFTY":"^NSEBANK","GOLD":"GC=F",
          "SILVER":"SI=F","CRUDEOIL":"CL=F","NASDAQ":"^IXIC","DOW JONES":"^DJI"}
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

def n500():
    try:
        r = requests.get("https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv", headers=UA, timeout=20)
        syms = [str(s).strip() for s in pd.read_csv(io.StringIO(r.text))["Symbol"] if str(s).strip()]
        if len(syms) > 300: return syms
    except Exception as e:
        print("nifty500 list fail", e)
    return NIFTY

def chunks(l, n): return [l[i:i + n] for i in range(0, len(l), n)]

def scan500():
    syms = n500(); src = "nifty500" if len(syms) > 300 else "nifty50"
    full = [s + ".NS" for s in syms]
    rows, brk, scan = [], [], []
    adv = dec = a20 = a50 = nd = 0
    for part in chunks(full, 100):
        try:
            df = yf.download(part, period="6mo", interval="1d", group_by="ticker",
                             progress=False, auto_adjust=False, threads=True)
        except Exception as e:
            print("scan fail", e); continue
        for s in part:
            try:
                d = df[s][["Open", "High", "Low", "Close", "Volume"]].dropna()
                if len(d) < 2: continue
                o, h, l, c, v = [float(x) for x in d.iloc[-1]]
                pc = float(d["Close"].iloc[-2]); chg = round((c / pc - 1) * 100, 2); name = s[:-3]
                rows.append({"name": name, "open": round(o, 2), "high": round(h, 2), "low": round(l, 2),
                             "price": round(c, 2), "chg": chg})
                if chg > 0: adv += 1
                elif chg < 0: dec += 1
                if len(d) < 60: continue
                cl, hi, vo = d["Close"], d["High"], d["Volume"]
                nd += 1
                a20 += int(c > float(cl.rolling(20).mean().iloc[-1]))
                a50 += int(c > float(cl.rolling(50).mean().iloc[-1]))
                va = float(vo.iloc[-21:-1].mean()); vr = round(v / va, 2) if va > 0 else 0
                if c > float(hi.iloc[-21:-1].max()):
                    brk.append({"name": name, "price": round(c, 2), "chg": chg, "vr": vr})
                # Chartink-type scan: Close crosses above SMA(High,55), Open < Close, RSI(14) crosses above 60
                sm = hi.rolling(55).mean(); r = rsi(cl)
                if (c > float(sm.iloc[-1]) and float(cl.iloc[-2]) <= float(sm.iloc[-2]) and o < c
                        and float(r.iloc[-1]) > 60 and float(r.iloc[-2]) <= 60):
                    scan.append({"name": name, "price": round(c, 2), "chg": chg,
                                 "rsi": round(float(r.iloc[-1]), 1), "vr": vr})
            except Exception:
                continue
    tol = 0.0003
    low = [r for r in rows if r["open"] > 0 and r["high"] > r["low"] and (r["open"] - r["low"]) / r["open"] <= tol]
    high = [r for r in rows if r["open"] > 0 and r["high"] > r["low"] and (r["high"] - r["open"]) / r["open"] <= tol]
    low.sort(key=lambda r: r["chg"], reverse=True); high.sort(key=lambda r: r["chg"])
    brk.sort(key=lambda r: r["vr"], reverse=True); scan.sort(key=lambda r: r["rsi"], reverse=True)
    return {"src": src, "scanned": len(rows), "low": low[:40], "high": high[:40], "brk": brk[:30], "scan": scan[:40],
            "adv": adv, "dec": dec, "above20": a20, "above50": a50, "nd": nd}

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
    prev = n["price"] / (1 + n["chg"] / 100)
    return {"vix": v["price"], "close": n["price"], "pts": round(pts, 1), "pct": round(pct, 2),
            "low": round(n["price"] - pts, 1), "high": round(n["price"] + pts, 1),
            "prev": round(prev, 1), "move": round(n["price"] - prev, 1)}

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
    avg = sum(scores.values()) / len(scores) if scores else 0
    buzz = sorted(({"name": s, "count": sum(1 for x in o if x["h"] != 0)} for s, o in res), key=lambda b: b["count"], reverse=True)
    return {"headlines": total, "stocks": len(res), "notable": len(rows), "rows": rows[:25], "sectors": secs,
            "avg": round(avg, 2), "buzz": [b for b in buzz if b["count"] > 0][:6]}

def first15():
    try:
        d = yf.Ticker("^NSEI").history(period="1d", interval="5m")
        d.index = d.index.tz_convert("Asia/Kolkata")
        w = d[(d.index.hour == 9) & (d.index.minute >= 15) & (d.index.minute < 30)]
        if len(w) < 3: return None
        return {"hi": round(float(w["High"].max()), 1), "lo": round(float(w["Low"].min()), 1)}
    except Exception:
        return None

def adx_trend():
    try:
        d = yf.Ticker("^NSEI").history(period="6mo", interval="1d").dropna()
        h, l, c = d["High"], d["Low"], d["Close"]
        up, dn = h.diff(), -l.diff()
        pdm = up.where((up > dn) & (up > 0), 0.0); ndm = dn.where((dn > up) & (dn > 0), 0.0)
        tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
        a = 1 / 14
        atr = tr.ewm(alpha=a, adjust=False).mean()
        pdi = 100 * pdm.ewm(alpha=a, adjust=False).mean() / atr
        ndi = 100 * ndm.ewm(alpha=a, adjust=False).mean() / atr
        adx = (100 * (pdi - ndi).abs() / (pdi + ndi)).ewm(alpha=a, adjust=False).mean()
        v = float(adx.iloc[-1]); last = float(c.iloc[-1])
        s20 = float(c.rolling(20).mean().iloc[-1]); s50 = float(c.rolling(50).mean().iloc[-1])
        return {"adx": round(v, 1), "state": "Trending" if v >= 25 else "Sideways" if v < 20 else "Weak trend",
                "dir": "Uptrend" if last > s20 > s50 else "Downtrend" if last < s20 < s50 else "Mixed",
                "hi20": round(float(h.tail(20).max()), 1), "lo20": round(float(l.tail(20).min()), 1),
                "open": round(float(d["Open"].iloc[-1]), 1), "prev": round(float(c.iloc[-2]), 1),
                "date": d.index[-1].strftime("%d %b"), "f15": first15()}
    except Exception as e:
        print("trend fail", e); return None

def retail_mood(sc, rng, small, mid, fno):
    parts = []
    def add(name, value, score, note):
        parts.append({"name": name, "value": value, "score": round(max(0, min(100, score))), "note": note})
    if rng: add("India VIX", rng["vix"], 100 - (rng["vix"] - 10) / 15 * 100, "VIX kam = befikri, zyada = dar")
    if sc["adv"] + sc["dec"] > 50:
        p = sc["adv"] / (sc["adv"] + sc["dec"]) * 100
        add("Aaj upar wale stocks", f"{p:.0f}%", p, "jitne zyada stocks upar, utna josh")
    if sc["nd"] > 50:
        p20 = sc["above20"] / sc["nd"] * 100; p50 = sc["above50"] / sc["nd"] * 100
        add("20 DMA ke upar stocks", f"{p20:.0f}%", p20, "short term ki taqat")
        add("50 DMA ke upar stocks", f"{p50:.0f}%", p50, "medium term ki taqat")
    rets = [(a["spark"][-1] / a["spark"][-6] - 1) * 100 for a in (small, mid) if a and len(a.get("spark", [])) >= 6]
    if rets:
        r5 = sum(rets) / len(rets)
        add("Small/Midcap, 5 din", f"{r5:+.1f}%", 50 + r5 * 10, "chhote stocks mein risk lene ka mood")
    if fno and fno.get("stocks"):
        add("News ka tone", f"{fno['avg']:+.1f}", 50 + fno["avg"] * 5, "headlines mein positive ya negative")
    if not parts: return None
    s = sum(p["score"] for p in parts) / len(parts)
    label = "Extreme Fear" if s < 25 else "Fear" if s < 45 else "Neutral" if s < 55 else "Greed" if s < 75 else "Extreme Greed"
    return {"score": round(s), "label": label, "parts": parts}

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
def first_ok(cands):
    for sym, label in cands:
        a = get(sym)
        if a: return {"name": label, **a}
    return None
# Smallcap/Midcap ke Yahoo symbols pakke confirm nahi hain, isliye kuch try hote hain
SMALL = first_ok([("^CNXSC", "NIFTY SMALLCAP 100"), ("NIFTYSMLCAP250.NS", "NIFTY SMALLCAP 250")])
MID = first_ok([("NIFTY_MIDCAP_100.NS", "NIFTY MIDCAP 100"), ("NIFTYMIDCAP150.NS", "NIFTY MIDCAP 150"), ("^NSEMDCP50", "NIFTY MIDCAP 50")])
data["assets"].insert(1, SMALL or {"name": "NIFTY SMALLCAP", "na": True})
data["assets"].insert(2, MID or {"name": "NIFTY MIDCAP", "na": True})
sc = scan500()
data["ohl"] = {k: sc[k] for k in ("src", "scanned", "low", "high")}
data["brk"] = sc["brk"]; data["scan"] = sc["scan"]
data["global"] = global_cues(); data["range"] = day_range(); data["fno"] = fno_watch(); data["trend"] = adx_trend()
data["mood"] = retail_mood(sc, data["range"], SMALL, MID, data["fno"])
json.dump(data, open("data.json", "w"), ensure_ascii=False)
print("saved", len(data["assets"]), "assets", len(stocks), "stocks", len(sectors), "sectors")
