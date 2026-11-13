from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio, time, math
import httpx
from datetime import datetime, timezone, timedelta

app=FastAPI(title="Dastyar Trade Scanner")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
TABDEAL="https://api-web.tabdeal.org/r"
WEB="https://api-web.tabdeal.org/r/plots"
# فهرست اولیه دارایی‌هایی که کاربر قبلاً در اهرم حرفه‌ای دیده؛ باید با فهرست رسمی قراردادهای اهرمی تطبیق داده شود.
WATCH=["BTC","DOT","SOL","ETHFI","HBAR","XLM","ADA","ZEC","XAUT","BMT","PEPE","PUMP","RENDER","ARB","TUT","PYTH","ACE","HEMI","TIA","KAITO","PROM","ARIA","AIN","ALLO","Q","QUACK"]

async def get_json(client,url,params=None):
    r=await client.get(url,params=params,timeout=15,headers={"User-Agent":"Mozilla/5.0","Origin":"https://tabdeal.org","Referer":"https://tabdeal.org/"})
    r.raise_for_status()
    return r.json()

def ema(vals,n):
    if len(vals)<n:return None
    k=2/(n+1); e=sum(vals[:n])/n
    for v in vals[n:]:e=v*k+e*(1-k)
    return e
def rsi(vals,n=14):
    if len(vals)<n+1:return 50
    dif=[vals[i]-vals[i-1] for i in range(1,len(vals))]
    gains=[max(x,0) for x in dif[-n:]]; losses=[max(-x,0) for x in dif[-n:]]
    ag=sum(gains)/n; al=sum(losses)/n
    return 100 if al==0 else 100-100/(1+ag/al)
def analyze(rows):
    rows=sorted(rows,key=lambda x:x[0])
    rows=[x for x in rows if all(v is not None for v in x[1:5])]
    if len(rows)<55: raise ValueError("کندل کافی نیست")
    closes=[x[4] for x in rows]; highs=[x[2] for x in rows]; lows=[x[3] for x in rows]; vols=[x[5] or 0 for x in rows]
    price=closes[-1]; e20=ema(closes,20); e50=ema(closes,50); rr=rsi(closes)
    e12=ema(closes,12); e26=ema(closes,26); macd=e12-e26
    sig=ema([ema(closes[:i+1],12)-ema(closes[:i+1],26) for i in range(25,len(closes))],9)
    hist=macd-(sig or 0)
    tr=[]
    for i in range(1,len(rows)):
        tr.append(max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])))
    atr=sum(tr[-14:])/min(14,len(tr))
    support=min(lows[-20:]); resistance=max(highs[-20:])
    vol_ok=vols[-1] >= (sum(vols[-21:-1])/20 if sum(vols[-21:-1]) else 0)
    long=0; short=0; why=[]
    if price>e20:long+=18
    else:short+=18
    if e20>e50:long+=22;why.append("EMA صعودی")
    else:short+=22;why.append("EMA نزولی")
    if rr>55:long+=14
    elif rr<45:short+=14
    if hist>0:long+=14
    else:short+=14
    if vol_ok:
        if closes[-1]>closes[-2]:long+=12
        elif closes[-1]<closes[-2]:short+=12
    # ساختار شکست/نزدیکی سطح؛ وزن محدود برای پرهیز از ادعای قطعیت
    if price>max(highs[-6:-1]):long+=20;why.append("شکست سقف کوتاه")
    elif price<min(lows[-6:-1]):short+=20;why.append("شکست کف کوتاه")
    else:
        if abs(price-support)<abs(resistance-price):long+=8
        else:short+=8
    signal="LONG" if long-short>=15 else "SHORT" if short-long>=15 else "NEUTRAL"
    score=max(long,short)
    stop=price-1.5*atr if signal=="LONG" else price+1.5*atr
    target=price+2*atr if signal=="LONG" else price-2*atr
    return {"price":price,"support":support,"resistance":resistance,"entry":price,"stop":stop,"target":target,"signal":signal,"score":min(100,score),"reason":f"RSI={rr:.1f} | {'، '.join(why) or 'روند ترکیبی'}"}
async def scan_coin(client,symbol):
    end=int(time.time()); start=end-100*60*60*4
    params={"symbol":f"{symbol}_USDT","resolution":"60","from":start,"to":end}
    try:
        data=await get_json(client,f"{TABDEAL}/plots/history/",params)
        rows=[[x.get("time"),float(x.get("open")),float(x.get("high")),float(x.get("low")),float(x.get("close")),float(x.get("volume") or 0)] for x in data.get("data",[])]
        a=analyze(rows)
        return {"symbol":symbol,**a}
    except Exception:
        return None
@app.get("/health")
async def health():return {"ok":True,"service":"Dastyar scanner"}
@app.get("/api/scan")
async def scan(min_score:int=70,limit:int=20):
    if min_score<1 or min_score>100: raise HTTPException(400,"min_score must be 1..100")
    async with httpx.AsyncClient() as client:
        tasks=[scan_coin(client,s) for s in WATCH]
        rows=await asyncio.gather(*tasks)
    results=[x for x in rows if x and x["score"]>=min_score]
    results.sort(key=lambda x:x["score"],reverse=True)
    return {"timestamp":datetime.now(timezone.utc).isoformat(),"results":results[:max(1,min(50,limit))],
            "note":"غربال اولیه بر اساس کندل عمومی ۱ساعته USDT؛ نه فهرست تأییدشده اهرم حرفه‌ای. داده‌ها و نمادها ممکن است تغییر کنند."}
