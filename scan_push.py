#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import base64, io, json, math, os, ssl, sys, time, urllib.request
from datetime import datetime, timezone
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

PUSHPLUS_TOKEN = os.environ["PUSHPLUS_TOKEN"]
BASE_SPOT = "https://data-api.binance.vision"
CTX = ssl.create_default_context()
HDR = {"User-Agent": "Mozilla/5.0"}
N = 26; MULT = 2.0; ATR_P = 14; SKEL_THR = 0.8
LOOKBACK = 2; INTERVAL = "1h"; KLIMIT = 120; KLINE_FETCH = 30; DKLIMIT = 36

def http_get_json(url, retries=3):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e: last = e; time.sleep(2.0)
    raise last

def notify(title, content):
    url = "https://www.pushplus.plus/send"
    payload = json.dumps({"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "html"})
    req = urllib.request.Request(url, data=payload.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read())
    return resp.get("code") == 200

def get_symbols():
    info = http_get_json(f"{BASE_SPOT}/api/v3/exchangeInfo")
    syms = [s["symbol"] for s in info["symbols"] if s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT" and s.get("isSpotTradingAllowed",True)]
    syms = [s for s in syms if not any(k in s for k in ("UP","DOWN","BULL","BEAR"))]
    return sorted(set(syms))

def fetch_klines(symbol, limit=KLIMIT):
    url = f"{BASE_SPOT}/api/v3/klines?symbol={symbol}&interval={INTERVAL}&limit={limit}"
    raw = http_get_json(url)
    return [{"t":int(r[0]),"o":float(r[1]),"h":float(r[2]),"l":float(r[3]),"c":float(r[4]),"v":float(r[5])} for r in raw]

def fetch_daily_klines(symbol, limit=DKLIMIT):
    url = f"{BASE_SPOT}/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}"
    raw = http_get_json(url)
    return [{"t":int(r[0]),"o":float(r[1]),"h":float(r[2]),"l":float(r[3]),"c":float(r[4]),"v":float(r[5])} for r in raw]

def compute(df):
    n=len(df); closes=[x["c"] for x in df]
    for i in range(n):
        if i<N-1: df[i]["upper"]=None; continue
        window=closes[i-N+1:i+1]; mid=sum(window)/N
        df[i]["upper"]=mid+MULT*math.sqrt(sum((x-mid)**2 for x in window)/N)
    tr=[0.0]*n
    for i in range(1,n): tr[i]=max(df[i]["h"]-df[i]["l"],abs(df[i]["h"]-closes[i-1]),abs(df[i]["l"]-closes[i-1]))
    atr=[0.0]*n
    if n>=ATR_P:
        atr[ATR_P-1]=sum(tr[1:ATR_P])/ATR_P
        for i in range(ATR_P,n): atr[i]=(atr[i-1]*(ATR_P-1)+tr[i])/ATR_P
    for i in range(n):
        df[i]["atr"]=atr[i]
        if atr[i] and atr[i]>0 and df[i].get("upper") is not None:
            body=abs(df[i]["c"]-df[i]["o"]); df[i]["batr"]=body/atr[i]
            df[i]["skel_up"]=(df[i]["batr"]>SKEL_THR) and (df[i]["c"]>df[i]["upper"])
        else: df[i]["batr"]=None; df[i]["skel_up"]=False
    return df

def draw_chart(symbol, bar_label):
    raw=fetch_klines(symbol, KLINE_FETCH)
    if len(raw)<26: return None
    bar_en="last" if chr(26368) in bar_label else "prev"
    df=pd.DataFrame(raw); df["dt"]=pd.to_datetime(df["t"],unit="ms"); df=df.set_index("dt").sort_index()
    sma=df["c"].rolling(N).mean(); std=df["c"].rolling(N).std()
    df["upper"]=sma+MULT*std; df["mid"]=sma; df["lower"]=sma-MULT*std
    ohlc=df[["o","h","l","c","v"]].copy(); ohlc.columns=["Open","High","Low","Close","Volume"]
    display=min(26,len(ohlc)); ohlc=ohlc.iloc[-display:]
    apds=[mpf.make_addplot(df["upper"].iloc[-display:],color="orange",width=1.2),
          mpf.make_addplot(df["mid"].iloc[-display:],color="blue",width=0.8,linestyle="--"),
          mpf.make_addplot(df["lower"].iloc[-display:],color="orange",width=1.2)]
    mc=mpf.make_marketcolors(up="#26a69a",down="#ef5350",edge="inherit",wick="inherit",volume="inherit")
    s=mpf.make_mpf_style(marketcolors=mc,gridstyle=":",y_on_right=False)
    fig,_=mpf.plot(ohlc,type="candle",style=s,addplot=apds,volume=True,
                    title=f"{symbol} 1h BOLL(26,2) Signal: {bar_en}",
                    returnfig=True,figsize=(10,6),datetime_format="%m-%d %H:%M",xrotation=30)
    buf=io.BytesIO(); fig.savefig(buf,format="png",dpi=90,bbox_inches="tight",facecolor="white"); plt.close(fig)
    buf.seek(0); return base64.b64encode(buf.read()).decode()

def draw_daily_chart(symbol):
    raw=fetch_daily_klines(symbol)
    if len(raw)<26: return None
    df=pd.DataFrame(raw); df["dt"]=pd.to_datetime(df["t"],unit="ms"); df=df.set_index("dt").sort_index()
    sma=df["c"].rolling(N).mean(); std=df["c"].rolling(N).std()
    df["upper"]=sma+MULT*std; df["mid"]=sma; df["lower"]=sma-MULT*std
    ohlc=df[["o","h","l","c","v"]].copy(); ohlc.columns=["Open","High","Low","Close","Volume"]
    display=min(30,len(ohlc)); ohlc=ohlc.iloc[-display:]
    apds=[mpf.make_addplot(df["upper"].iloc[-display:],color="orange",width=1.2),
          mpf.make_addplot(df["mid"].iloc[-display:],color="blue",width=0.8,linestyle="--"),
          mpf.make_addplot(df["lower"].iloc[-display:],color="orange",width=1.2)]
    mc=mpf.make_marketcolors(up="#26a69a",down="#ef5350",edge="inherit",wick="inherit",volume="inherit")
    s=mpf.make_mpf_style(marketcolors=mc,gridstyle=":",y_on_right=False)
    fig,_=mpf.plot(ohlc,type="candle",style=s,addplot=apds,volume=True,
                    title=f"{symbol} 1d BOLL(26,2)",
                    returnfig=True,figsize=(10,6),datetime_format="%Y-%m-%d",xrotation=30)
    buf=io.BytesIO(); fig.savefig(buf,format="png",dpi=90,bbox_inches="tight",facecolor="white"); plt.close(fig)
    buf.seek(0); return base64.b64encode(buf.read()).decode()

def build_html(hits, charts, daily_charts):
    lines=[f"<h3>éª¨æ¶Kçªç ´å¸æä¸è½¨</h3><p>ç°è´§1h | æè¿2æ ¹ | {len(hits)}å½ä¸­ | {datetime.now(timezone.utc).strftime('%m-%d %H:%M UTC')}</p>"]
    lines.append('<table border="1" cellpadding="3" cellspacing="0" style="border-collapse:collapse;font-size:12px;"><tr style="background:#f0f0f0;"><th>æ ç</th><th>Kçº¿</th><th>Close</th><th>ä¸è½¨</th><th>B-ATR</th><th>å®ä½%</th><th>è¶ä¸è½¨%</th></tr>')
    rows_sorted=sorted(hits,key=lambda r:r["batr"],reverse=True); hq=[]
    for r in rows_sorted:
        m=""
        if r["batr"]>1.5 and r["pct_above_upper"]>1.0: m=" â"; hq.append(r["symbol"])
        lines.append(f'<tr><td>{r["symbol"]}{m}</td><td>{r["bar"]}</td><td>{r["close"]}</td><td>{r["upper"]}</td><td>{r["batr"]}</td><td>{r["body_pct"]}%</td><td>{r["pct_above_upper"]}%</td></tr>')
    lines.append("</table>")
    if hq: lines.append(f'<p style="color:#d32f2f;"><b>é«è´¨éï¼{"ã".join(hq)}</b></p>')
    if charts:
        lines.append("<hr><h4>1h Kçº¿å¾</h4>")
        for ch in charts: lines.append(f"<p><b>{ch['symbol']}</b></p><img src=\"data:image/png;base64,{ch['b64']}\" style=\"max-width:100%;\">")
    if daily_charts:
        lines.append("<hr><h4>æ¥çº¿å¾</h4>")
        for dc in daily_charts: lines.append(f"<p><b>{dc['symbol']}</b></p><img src=\"data:image/png;base64,{dc['b64']}\" style=\"max-width:100%;\">")
    return "".join(lines)

def scan():
    symbols=get_symbols()
    print(f"æ«æ {len(symbols)} ä¸ªç°è´§ USDT å¯¹")
    hits=[]
    for i,sym in enumerate(symbols,1):
        try:
            df=fetch_klines(sym)
            if len(df)<N+5: continue
            compute(df); tail=df[-LOOKBACK:]
            for pos,row in zip(range(-LOOKBACK,0),tail):
                if row.get("skel_up"):
                    hits.append({"symbol":sym,
                        "bar":"ææ°ä¸æ ¹" if pos==-1 else ("åä¸æ ¹" if pos==-2 else f"å{-pos}æ ¹"),
                        "close":round(row["c"],8),"upper":round(row["upper"],8),
                        "batr":round(row["batr"],3),
                        "body_pct":round(abs(row["c"]-row["o"])/row["c"]*100,3),
                        "pct_above_upper":round((row["c"]/row["upper"]-1)*100,3)})
        except: pass
        if i%50==0: print(f"  {i}/{len(symbols)}")
    hits.sort(key=lambda h:(0 if "ææ°" in h["bar"] else 1,-h["batr"]))
    return hits

def main():
    hits=scan()
    if not hits: notify("éª¨æ¶Kæ«æï¼æ å½ä¸­","<p>æ¬æ¬¡æªå½ä¸­</p>"); return
    print(f"å½ä¸­ {len(hits)} ä¸ª"); charts=[]; daily_charts=[]
    hq_syms={h["symbol"] for h in hits if h["batr"]>1.5 and h["pct_above_upper"]>1.0}
    for h in hits:
        if h["symbol"] not in hq_syms: continue
        try:
            b64=draw_chart(h["symbol"],h["bar"])
            if b64: charts.append({"symbol":h["symbol"],"bar":h["bar"],"b64":b64})
            db64=draw_daily_chart(h["symbol"])
            if db64: daily_charts.append({"symbol":h["symbol"],"b64":db64})
        except Exception as e: print(f"  {h['symbol']}: {e}")
    html=build_html(hits,charts,daily_charts)
    notify("éª¨æ¶Kçªç ´ä¸è½¨æ«æ",html)
    for h in sorted(hits,key=lambda r:r["batr"],reverse=True):
        m=" *" if h["batr"]>1.5 and h["pct_above_upper"]>1.0 else ""
        print(f"{h['symbol']:12s} batr={h['batr']} è¶ä¸è½¨={h['pct_above_upper']}%{m}")

if __name__=="__main__":
    main()
