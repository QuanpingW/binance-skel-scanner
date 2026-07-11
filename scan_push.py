#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""骨架K突破布林上轨/下轨扫描 + PushPlus推送（现货Top160成交量）"""
import base64, io, json, math, os, ssl, sys, time, urllib.request
from datetime import datetime, timezone
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

PUSHPLUS_TOKEN = os.environ["PUSHPLUS_TOKEN"]
BASE_URL = "https://data-api.binance.vision"
CTX = ssl.create_default_context()
HDR = {"User-Agent": "Mozilla/5.0"}
N = 26; MULT = 2.0; ATR_P = 14; SKEL_THR = 0.8
LOOKBACK = 2; INTERVAL = "1h"; KLIMIT = 120; KLINE_FETCH = 30; DKLIMIT = 36
TOP_N = 160

def http_get_json(url, retries=3):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(2.0)
    raise last

def notify(title, content):
    url = "https://www.pushplus.plus/send"
    payload = json.dumps({"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "html"})
    req = urllib.request.Request(url, data=payload.encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read())
    return resp.get("code") == 200

def get_top_symbols(n=TOP_N):
    """获取24h成交额排名前N的USDT交易对"""
    print(f"获取24h成交额排名...")
    tickers = http_get_json(f"{BASE_URL}/api/v3/ticker/24hr")
    usdt = [t for t in tickers if t["symbol"].endswith("USDT") and not any(k in t["symbol"] for k in ("UP","DOWN","BULL","BEAR"))]
    usdt.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
    top = [t["symbol"] for t in usdt[:n]]
    print(f"Top{n}: 总{len(usdt)}个USDT对，取前{n}，榜首{top[0]} vol={float(usdt[0]['quoteVolume']):.0f}")
    return top

def fetch_klines(symbol, limit=KLIMIT):
    url = f"{BASE_URL}/api/v3/klines?symbol={symbol}&interval={INTERVAL}&limit={limit}"
    raw = http_get_json(url)
    return [{"t": int(r[0]), "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]), "v": float(r[5])} for r in raw]

def fetch_daily_klines(symbol, limit=DKLIMIT):
    url = f"{BASE_URL}/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}"
    raw = http_get_json(url)
    return [{"t": int(r[0]), "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]), "v": float(r[5])} for r in raw]

def compute(df):
    """计算BOLL上下轨、ATR、B-ATR、骨架K突破信号"""
    n = len(df)
    closes = [x["c"] for x in df]

    # 计算BOLL上下轨（同时算upper和lower）
    for i in range(n):
        if i < N - 1:
            df[i]["upper"] = None
            df[i]["lower"] = None
            continue
        window = closes[i - N + 1 : i + 1]
        mid = sum(window) / N
        std = math.sqrt(sum((x - mid) ** 2 for x in window) / N)
        df[i]["upper"] = mid + MULT * std
        df[i]["lower"] = mid - MULT * std

    # ATR
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(df[i]["h"] - df[i]["l"], abs(df[i]["h"] - closes[i - 1]), abs(df[i]["l"] - closes[i - 1]))
    atr = [0.0] * n
    if n >= ATR_P:
        atr[ATR_P - 1] = sum(tr[1:ATR_P]) / ATR_P
        for i in range(ATR_P, n):
            atr[i] = (atr[i - 1] * (ATR_P - 1) + tr[i]) / ATR_P

    # B-ATR + 突破信号
    for i in range(n):
        df[i]["atr"] = atr[i]
        if atr[i] and atr[i] > 0 and df[i].get("upper") is not None:
            body = abs(df[i]["c"] - df[i]["o"])
            df[i]["batr"] = body / atr[i]
            df[i]["skel_up"] = (df[i]["batr"] > SKEL_THR) and (df[i]["c"] > df[i]["upper"])
            df[i]["skel_down"] = (df[i]["batr"] > SKEL_THR) and (df[i]["c"] < df[i]["lower"])
        else:
            df[i]["batr"] = None
            df[i]["skel_up"] = False
            df[i]["skel_down"] = False
    return df

def draw_chart(symbol, bar_label, direction="up"):
    """绘制1h K线+BOLL图"""
    raw = fetch_klines(symbol, KLINE_FETCH)
    if len(raw) < 26:
        return None
    bar_en = "last" if "最新" in bar_label else "prev"
    df = pd.DataFrame(raw)
    df["dt"] = pd.to_datetime(df["t"], unit="ms")
    df = df.set_index("dt").sort_index()
    sma = df["c"].rolling(N).mean()
    std = df["c"].rolling(N).std()
    df["upper"] = sma + MULT * std
    df["mid"] = sma
    df["lower"] = sma - MULT * std
    ohlc = df[["o", "h", "l", "c", "v"]].copy()
    ohlc.columns = ["Open", "High", "Low", "Close", "Volume"]
    display = min(26, len(ohlc))
    ohlc = ohlc.iloc[-display:]
    apds = [
        mpf.make_addplot(df["upper"].iloc[-display:], color="orange", width=1.2),
        mpf.make_addplot(df["mid"].iloc[-display:], color="blue", width=0.8, linestyle="--"),
        mpf.make_addplot(df["lower"].iloc[-display:], color="orange", width=1.2),
    ]
    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit", wick="inherit", volume="inherit")
    s = mpf.make_mpf_style(marketcolors=mc, gridstyle=":", y_on_right=False)
    direction_label = "Break Up" if direction == "up" else "Break Down"
    fig, _ = mpf.plot(
        ohlc, type="candle", style=s, addplot=apds, volume=True,
        title=f"{symbol} 1h BOLL(26,2) {direction_label}: {bar_en}",
        returnfig=True, figsize=(10, 6), datetime_format="%m-%d %H:%M", xrotation=30,
    )
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=90, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()

def draw_daily_chart(symbol):
    """绘制日线K线+BOLL图"""
    raw = fetch_daily_klines(symbol)
    if len(raw) < 26:
        return None
    df = pd.DataFrame(raw)
    df["dt"] = pd.to_datetime(df["t"], unit="ms")
    df = df.set_index("dt").sort_index()
    sma = df["c"].rolling(N).mean()
    std = df["c"].rolling(N).std()
    df["upper"] = sma + MULT * std
    df["mid"] = sma
    df["lower"] = sma - MULT * std
    ohlc = df[["o", "h", "l", "c", "v"]].copy()
    ohlc.columns = ["Open", "High", "Low", "Close", "Volume"]
    display = min(30, len(ohlc))
    ohlc = ohlc.iloc[-display:]
    apds = [
        mpf.make_addplot(df["upper"].iloc[-display:], color="orange", width=1.2),
        mpf.make_addplot(df["mid"].iloc[-display:], color="blue", width=0.8, linestyle="--"),
        mpf.make_addplot(df["lower"].iloc[-display:], color="orange", width=1.2),
    ]
    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit", wick="inherit", volume="inherit")
    s = mpf.make_mpf_style(marketcolors=mc, gridstyle=":", y_on_right=False)
    fig, _ = mpf.plot(
        ohlc, type="candle", style=s, addplot=apds, volume=True,
        title=f"{symbol} 1d BOLL(26,2)",
        returnfig=True, figsize=(10, 6), datetime_format="%Y-%m-%d", xrotation=30,
    )
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=90, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()

def build_table(rows, label):
    """生成HTML表格片段"""
    if not rows:
        return ""
    lines = [f"<h4>{label}（{len(rows)}个）</h4>"]
    lines.append('<table border="1" cellpadding="3" cellspacing="0" style="border-collapse:collapse;font-size:12px;">')
    lines.append('<tr style="background:#f0f0f0;"><th>标的</th><th>K线</th><th>Close</th><th>轨值</th><th>B-ATR</th><th>实体%</th><th>超轨%</th></tr>')
    rows_sorted = sorted(rows, key=lambda r: r["batr"], reverse=True)
    hq = []
    for r in rows_sorted:
        m = ""
        if r["batr"] > 1.5 and r["pct_above_band"] > 1.0:
            m = " ★"
            hq.append(r["symbol"])
        lines.append(f'<tr><td>{r["symbol"]}{m}</td><td>{r["bar"]}</td><td>{r["close"]}</td><td>{r["band_val"]}</td><td>{r["batr"]}</td><td>{r["body_pct"]}%</td><td>{r["pct_above_band"]}%</td></tr>')
    lines.append("</table>")
    if hq:
        lines.append(f'<p style="color:#d32f2f;"><b>高质量：{"、".join(hq)}</b></p>')
    return "".join(lines)

def build_chart_section(charts, label):
    """生成图表HTML片段"""
    if not charts:
        return ""
    lines = [f"<hr><h4>{label}</h4>"]
    for ch in charts:
        lines.append(f"<p><b>{ch['symbol']}</b></p><img src=\"data:image/png;base64,{ch['b64']}\" style=\"max-width:100%;\">")
    return "".join(lines)

def build_html(up_hits, down_hits, up_charts, down_charts, up_daily, down_daily):
    """生成推送HTML"""
    now_str = datetime.now(timezone.utc).strftime("%m-%d %H:%M UTC")
    total = len(up_hits) + len(down_hits)
    lines = [
        f"<h3>骨架K突破布林轨</h3>",
        f"<p>现货1h | Top{TOP_N}成交量 | 最近2根 | 共{total}命中（上轨{len(up_hits)}/下轨{len(down_hits)}）| {now_str}</p>",
    ]

    if up_hits:
        lines.append(build_table(up_hits, "突破上轨"))
    if down_hits:
        lines.append(build_table(down_hits, "突破下轨"))

    # 1h 图
    if up_charts:
        lines.append(build_chart_section(up_charts, "突破上轨 - 1h K线"))
    if down_charts:
        lines.append(build_chart_section(down_charts, "突破下轨 - 1h K线"))

    # 日线图
    if up_daily:
        lines.append(build_chart_section(up_daily, "突破上轨 - 日线"))
    if down_daily:
        lines.append(build_chart_section(down_daily, "突破下轨 - 日线"))

    return "".join(lines)

def scan(symbols):
    """扫描骨架K突破信号"""
    up_hits = []
    down_hits = []
    for i, sym in enumerate(symbols, 1):
        try:
            df = fetch_klines(sym)
            if len(df) < N + 5:
                continue
            compute(df)
            tail = df[-LOOKBACK:]
            for pos, row in zip(range(-LOOKBACK, 0), tail):
                bar_label = "最新一根" if pos == -1 else ("前一根" if pos == -2 else f"前{-pos}根")
                base = {
                    "symbol": sym,
                    "bar": bar_label,
                    "close": round(row["c"], 8),
                    "batr": round(row["batr"], 3),
                    "body_pct": round(abs(row["c"] - row["o"]) / row["c"] * 100, 3),
                }
                if row.get("skel_up"):
                    up_hits.append({
                        **base,
                        "band_val": round(row["upper"], 8),
                        "pct_above_band": round((row["c"] / row["upper"] - 1) * 100, 3),
                    })
                if row.get("skel_down"):
                    down_hits.append({
                        **base,
                        "band_val": round(row["lower"], 8),
                        "pct_above_band": round((row["c"] / row["lower"] - 1) * 100, 3),
                    })
        except Exception:
            pass
        if i % 40 == 0:
            print(f"  {i}/{len(symbols)}")
    up_hits.sort(key=lambda h: (0 if "最新" in h["bar"] else 1, -h["batr"]))
    down_hits.sort(key=lambda h: (0 if "最新" in h["bar"] else 1, -h["batr"]))
    return up_hits, down_hits

def gen_charts(hits, direction):
    """为高质量命中生成图表"""
    charts_1h = []
    charts_daily = []
    hq_syms = {h["symbol"] for h in hits if h["batr"] > 1.5 and h["pct_above_band"] > 1.0}
    for h in hits:
        if h["symbol"] not in hq_syms:
            continue
        try:
            b64 = draw_chart(h["symbol"], h["bar"], direction)
            if b64:
                charts_1h.append({"symbol": h["symbol"], "b64": b64})
            db64 = draw_daily_chart(h["symbol"])
            if db64:
                charts_daily.append({"symbol": h["symbol"], "b64": db64})
        except Exception as e:
            print(f"  chart {h['symbol']}: {e}")
    return charts_1h, charts_daily

def main():
    # 1. 获取Top160成交量交易对
    symbols = get_top_symbols(TOP_N)
    print(f"扫描 {len(symbols)} 个现货 USDT 对（Top{TOP_N}成交量）")

    # 2. 扫描
    up_hits, down_hits = scan(symbols)
    total = len(up_hits) + len(down_hits)
    if total == 0:
        notify("骨架K扫描：无命中", f"<p>本次扫描Top{TOP_N}成交量，无命中</p>")
        return

    print(f"命中: 上轨{len(up_hits)} + 下轨{len(down_hits)} = {total}")

    # 3. 生成图表（仅高质量）
    up_charts, up_daily = gen_charts(up_hits, "up")
    down_charts, down_daily = gen_charts(down_hits, "down")

    # 4. 构建HTML并推送
    html = build_html(up_hits, down_hits, up_charts, down_charts, up_daily, down_daily)
    notify("骨架K突破轨扫描", html)

    # 5. 日志输出
    if up_hits:
        print("--- 突破上轨 ---")
        for h in up_hits:
            m = " ★" if h["batr"] > 1.5 and h["pct_above_band"] > 1.0 else ""
            print(f"  {h['symbol']:12s} batr={h['batr']} 超上轨={h['pct_above_band']}%{m}")
    if down_hits:
        print("--- 突破下轨 ---")
        for h in down_hits:
            m = " ★" if h["batr"] > 1.5 and h["pct_above_band"] > 1.0 else ""
            print(f"  {h['symbol']:12s} batr={h['batr']} 破下轨={h['pct_above_band']}%{m}")

if __name__ == "__main__":
    main()
