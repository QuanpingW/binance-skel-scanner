#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gate.io USDT永续合约骨架K突破BOLL扫描
纯Python标准库(urllib) | 零第三方依赖 | 内联SVG图表
扫描1h K线 | Top160成交量 | 上轨+下轨双向信号
"""
import json, math, os, ssl, sys, time, urllib.request
from datetime import datetime, timezone

# === 配置 ===
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "YOUR_TOKEN_HERE")
BASE_URL = "https://api.gateio.ws/api/v4/futures/usdt"
TOP_N = 160
N_BOLL = 26
MULT = 2.0
ATR_PERIOD = 14
SKEL_THR = 0.8
LOOKBACK = 2
INTERVAL = "1h"
KLIMIT = 120
DKLIMIT = 60
CHART_CANDLES = 60
REQ_DELAY = 0.08

CTX = ssl.create_default_context()
HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# === HTTP 工具 ===
def http_get(url, retries=2):
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw)
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5)
    raise last_err

def notify_pushplus(title, content):
    """PushPlus 推送 HTML 内容"""
    url = "https://www.pushplus.plus/send"
    payload = json.dumps({"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "html"})
    data = payload.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp.get("code") == 200

# === 数据获取 ===
def get_top_contracts(n=TOP_N):
    """获取24h成交额排名前N的USDT永续合约"""
    print("获取 Gate.io 合约24h行情...")
    tickers = http_get(f"{BASE_URL}/tickers")
    usdt = [t for t in tickers if t["contract"].endswith("_USDT")]
    usdt.sort(key=lambda t: float(t.get("volume_24h_quote", 0)), reverse=True)
    print(f"  共 {len(usdt)} 个 USDT 合约，取前 {n}")
    if usdt:
        top_vol = float(usdt[0].get("volume_24h_quote", 0))
        print(f"  榜首: {usdt[0]['contract']} vol={top_vol:.0f}")
    return usdt[:n]

def fetch_klines(contract, interval, limit):
    """获取K线数据"""
    url = f"{BASE_URL}/candlesticks?contract={contract}&interval={interval}&limit={limit}"
    raw = http_get(url)
    klines = []
    for r in raw:
        klines.append({
            "t": int(float(r["t"])),
            "o": float(r["o"]),
            "h": float(r["h"]),
            "l": float(r["l"]),
            "c": float(r["c"]),
            "v": float(r["v"]),
        })
    return klines

# === 指标计算 ===
def compute_indicators(klines):
    """计算 BOLL(26,2) + ATR(14) + 骨架K信号"""
    n = len(klines)
    closes = [k["c"] for k in klines]

    # BOLL 上下轨
    for i in range(n):
        if i < N_BOLL - 1:
            klines[i]["upper"] = None
            klines[i]["mid"] = None
            klines[i]["lower"] = None
            continue
        window = closes[i - N_BOLL + 1 : i + 1]
        mid = sum(window) / N_BOLL
        variance = sum((x - mid) ** 2 for x in window) / N_BOLL  # ddof=0
        std = math.sqrt(variance)
        klines[i]["upper"] = mid + MULT * std
        klines[i]["mid"] = mid
        klines[i]["lower"] = mid - MULT * std

    # ATR (Wilder 平滑)
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(
            klines[i]["h"] - klines[i]["l"],
            abs(klines[i]["h"] - closes[i - 1]),
            abs(klines[i]["l"] - closes[i - 1]),
        )
    atr = [0.0] * n
    if n >= ATR_PERIOD:
        atr[ATR_PERIOD - 1] = sum(tr[1:ATR_PERIOD]) / ATR_PERIOD
        for i in range(ATR_PERIOD, n):
            atr[i] = (atr[i - 1] * (ATR_PERIOD - 1) + tr[i]) / ATR_PERIOD

    # 骨架K信号
    for i in range(n):
        klines[i]["atr"] = atr[i]
        if atr[i] and atr[i] > 0 and klines[i].get("upper") is not None:
            body = abs(klines[i]["c"] - klines[i]["o"])
            batr = body / atr[i]
            klines[i]["batr"] = batr
            klines[i]["skel_up"] = (batr > SKEL_THR) and (klines[i]["c"] > klines[i]["upper"])
            klines[i]["skel_down"] = (batr > SKEL_THR) and (klines[i]["c"] < klines[i]["lower"])
        else:
            klines[i]["batr"] = None
            klines[i]["skel_up"] = False
            klines[i]["skel_down"] = False
    return klines

# === 扫描 ===
def scan_contracts(contracts):
    """扫描所有合约的骨架K信号"""
    up_hits = []
    down_hits = []
    total = len(contracts)
    for idx, c in enumerate(contracts, 1):
        contract = c["contract"]
        vol_24h = float(c.get("volume_24h_quote", 0))
        try:
            klines = fetch_klines(contract, INTERVAL, KLIMIT)
            if len(klines) < N_BOLL + 5:
                continue
            compute_indicators(klines)
            tail = klines[-LOOKBACK:]
            for pos, k in zip(range(-LOOKBACK, 0), tail):
                bar_label = "最新一根" if pos == -1 else ("前一根" if pos == -2 else f"前{-pos}根")
                base = {
                    "contract": contract,
                    "bar": bar_label,
                    "close": round(k["c"], 6),
                    "batr": round(k["batr"], 3) if k["batr"] else 0,
                    "body_pct": round(abs(k["c"] - k["o"]) / k["c"] * 100, 3),
                    "vol_24h": vol_24h,
                }
                if k.get("skel_up") and k["upper"]:
                    up_hits.append({
                        **base,
                        "band_val": round(k["upper"], 6),
                        "pct_above_band": round((k["c"] / k["upper"] - 1) * 100, 3),
                        "signal": "up",
                    })
                if k.get("skel_down") and k["lower"]:
                    down_hits.append({
                        **base,
                        "band_val": round(k["lower"], 6),
                        "pct_above_band": round((k["c"] / k["lower"] - 1) * 100, 3),
                        "signal": "down",
                    })
        except Exception as e:
            print(f"  [{idx}/{total}] {contract} 失败: {e}")
            continue
        if idx % 40 == 0:
            print(f"  [{idx}/{total}] 已扫描...")
        time.sleep(REQ_DELAY)

    up_hits.sort(key=lambda h: (0 if "最新" in h["bar"] else 1, -h["batr"]))
    down_hits.sort(key=lambda h: (0 if "最新" in h["bar"] else 1, -h["batr"]))
    return up_hits, down_hits

# === SVG 图表绘制 ===
def draw_svg_chart(klines, title, signal_idx=None, width=1000, price_h=420, vol_h=100):
    """纯Python生成内联SVG蜡烛图+BOLL轨"""
    display = klines[-CHART_CANDLES:] if len(klines) > CHART_CANDLES else klines
    n = len(display)
    if n < 26:
        return f"<p>数据不足({n}根)，至少需要26根</p>"

    margin_left, margin_right, margin_top, margin_bot = 60, 20, 30, 30
    gap = 24
    chart_w = width - margin_left - margin_right
    chart_h = price_h - margin_top - margin_bot
    total_h = price_h + vol_h + gap

    # 数据范围
    all_prices = []
    for k in display:
        all_prices.extend([k["h"], k["l"], k.get("upper", 0) or 0, k.get("lower", 0) or 0])
    all_prices = [p for p in all_prices if p and p > 0]
    if not all_prices:
        return "<p>价格数据异常</p>"
    price_min = min(all_prices)
    price_max = max(all_prices)
    price_range = price_max - price_min or 1
    price_min -= price_range * 0.05
    price_max += price_range * 0.05
    price_range = price_max - price_min

    vol_max = max(k["v"] for k in display) or 1

    def px(idx):
        """K线索引 → chart X 坐标（蜡烛中心）"""
        return margin_left + (idx + 0.5) * chart_w / n

    def py(val):
        """价格 → chart Y"""
        return margin_top + (price_max - val) / price_range * chart_h

    def vy(val):
        """成交量 → vol chart Y"""
        return price_h + gap + vol_h - (val / vol_max * vol_h * 0.9)

    candle_w = max(1, chart_w / n * 0.6)

    # BOLL 连线
    boll_lines = []
    for band, color in [("upper", "#ff9800"), ("mid", "#2196f3"), ("lower", "#ff9800")]:
        pts = []
        for i, k in enumerate(display):
            if k.get(band) is not None:
                pts.append(f"{px(i):.1f},{py(k[band]):.1f}")
        style = "stroke-dasharray:6,3" if band == "mid" else ""
        boll_lines.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="1.2" {style}/>')

    # 蜡烛
    candles = []
    for i, k in enumerate(display):
        x = px(i)
        color = "#26a69a" if k["c"] >= k["o"] else "#ef5350"
        wick_x = f'<line x1="{x:.1f}" y1="{py(k["h"]):.1f}" x2="{x:.1f}" y2="{py(k["l"]):.1f}" stroke="{color}" stroke-width="1"/>'
        body_top = max(k["c"], k["o"])
        body_bot = min(k["c"], k["o"])
        body_h = max(1, py(body_bot) - py(body_top))
        body = f'<rect x="{x - candle_w/2:.1f}" y="{py(body_top):.1f}" width="{candle_w:.1f}" height="{body_h:.1f}" fill="{color}"/>'
        candles.append(f"{wick_x}\n    {body}")

    # 信号标记（黄色圆圈）
    signal_tags = ""
    if signal_idx is not None and 0 <= signal_idx < n:
        sx = px(signal_idx)
        sy = py(display[signal_idx]["c"])
        signal_tags = f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="6" fill="none" stroke="#ffeb3b" stroke-width="2.5"/>'

    # 成交量柱
    vol_bars = []
    for i, k in enumerate(display):
        x = px(i)
        vcol = "#26a69a" if k["c"] >= k["o"] else "#ef5350"
        vol_bars.append(f'<rect x="{x - candle_w/2:.1f}" y="{vy(k["v"]):.1f}" width="{candle_w:.1f}" height="{vol_h * 0.9 * k["v"] / vol_max:.1f}" fill="{vcol}" opacity="0.5"/>')

    # Y轴刻度
    y_ticks = ""
    for i in range(6):
        val = price_min + price_range * i / 5
        y = py(val)
        y_ticks += f'<line x1="{margin_left - 5}" y1="{y:.1f}" x2="{margin_left}" y2="{y:.1f}" stroke="#666" stroke-width="0.5"/>\n'
        y_ticks += f'<text x="{margin_left - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#999">{val:.4f}</text>\n'

    svg = f'''<svg width="{width}" height="{total_h}" xmlns="http://www.w3.org/2000/svg" style="background:#1a1a2e;font-family:monospace;">
  <rect width="{width}" height="{total_h}" fill="#1a1a2e"/>
  <text x="{width/2:.0f}" y="18" text-anchor="middle" font-size="13" fill="#ccc" font-weight="bold">{title}</text>
  <line x1="{margin_left}" y1="{margin_top}" x2="{margin_left + chart_w}" y2="{margin_top}" stroke="#333" stroke-width="0.5"/>
  <line x1="{margin_left}" y1="{price_h - margin_bot}" x2="{margin_left + chart_w}" y2="{price_h - margin_bot}" stroke="#333" stroke-width="0.5"/>
  {y_ticks}
  {chr(10).join("  " + l for l in boll_lines)}
  {chr(10).join("  " + c for c in candles)}
  {signal_tags}
  {chr(10).join("  " + v for v in vol_bars)}
  <line x1="{margin_left}" y1="{price_h + gap}" x2="{margin_left + chart_w}" y2="{price_h + gap}" stroke="#333" stroke-width="0.5"/>
</svg>'''
    return svg

def format_vol(v):
    """格式化成交额"""
    if v >= 1e9:
        return f"{v/1e9:.2f}B"
    elif v >= 1e6:
        return f"{v/1e6:.2f}M"
    elif v >= 1e3:
        return f"{v/1e3:.2f}K"
    return f"{v:.0f}"

# === HTML 构建（PushPlus用）===
def build_table(rows, label, direction):
    """生成HTML表格"""
    if not rows:
        return ""
    emoji = "🔴" if direction == "up" else "🟢"
    lines = [f"<h4>{emoji} {label}（{len(rows)}个）</h4>"]
    lines.append('<table border="1" cellpadding="3" cellspacing="0" style="border-collapse:collapse;font-size:12px;width:100%;">')
    lines.append('<tr style="background:#f0f0f0;"><th>合约</th><th>K线</th><th>Close</th><th>轨值</th><th>B-ATR</th><th>实体%</th><th>超轨%</th><th>24h成交</th></tr>')
    for r in sorted(rows, key=lambda x: x["batr"], reverse=True):
        m = " ★" if r["batr"] > 1.5 and r["pct_above_band"] > 1.0 else ""
        lines.append(
            f'<tr><td><b>{r["contract"]}</b>{m}</td>'
            f'<td>{r["bar"]}</td><td>{r["close"]}</td><td>{r["band_val"]}</td>'
            f'<td>{r["batr"]}</td><td>{r["body_pct"]}%</td><td>{r["pct_above_band"]}%</td>'
            f'<td>{format_vol(r["vol_24h"])}</td></tr>'
        )
    lines.append("</table>")
    hq = [r["contract"] for r in rows if r["batr"] > 1.5 and r["pct_above_band"] > 1.0]
    if hq:
        lines.append(f'<p style="color:#d32f2f;"><b>高质量：{"、".join(hq)}</b></p>')
    return "".join(lines)

def build_html(up_hits, down_hits, charts_html=""):
    """构建推送HTML（纯文字表格，不嵌大图）"""
    now_str = datetime.now(timezone.utc).strftime("%m-%d %H:%M UTC")
    total = len(up_hits) + len(down_hits)
    lines = [
        f"<h3>Gate.io 骨架K突破BOLL</h3>",
        f"<p>USDT永续 | 1h | Top{TOP_N}成交 | 最近2根 | 命中{total}（上{len(up_hits)}/下{len(down_hits)}）| {now_str}</p>",
    ]
    if up_hits:
        lines.append(build_table(up_hits, "突破上轨", "up"))
    if down_hits:
        lines.append(build_table(down_hits, "突破下轨", "down"))
    if not up_hits and not down_hits:
        lines.append("<p>本次扫描无命中</p>")
    return "".join(lines)

def build_scan_html(up_hits, down_hits, charts):
    """构建完整扫描HTML文档（含SVG图表，用于存档）"""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(up_hits) + len(down_hits)
    lines = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<style>body{background:#0d1117;color:#c9d1d9;font-family:monospace;padding:20px;max-width:1100px;margin:auto}",
        "h3{color:#58a6ff}h4{color:#f0f0f0;margin-top:24px}",
        "table{border-collapse:collapse;width:100%;margin:8px 0;font-size:12px}",
        "th{background:#21262d;padding:6px 8px;text-align:left}td{padding:4px 8px;border:1px solid #30363d}",
        ".up{color:#ff7b72}.down{color:#7ee787}p{margin:4px 0}</style></head><body>",
        f"<h3>Gate.io 骨架K突破BOLL扫描</h3>",
        f"<p>USDT永续 | 1h | Top{TOP_N}成交 | 最近2根 | 命中{total}（上{len(up_hits)}/下{len(down_hits)}）| {now_str}</p>",
    ]
    if up_hits:
        lines.append(build_table(up_hits, "突破上轨", "up"))
    if down_hits:
        lines.append(build_table(down_hits, "突破下轨", "down"))
    if not charts:
        lines.append("<p>本次扫描无高质量信号图表</p>")
    else:
        for ch in charts:
            contract = ch["contract"]
            vol_str = format_vol(ch["vol_24h"])
            signal_tag = "突破上轨" if ch["signal"] == "up" else "突破下轨"
            lines.append(f"<hr><h4>{contract} | {signal_tag} | 24h成交: {vol_str} USDT</h4>")
            if ch.get("svg_1h"):
                lines.append(f"<p>1h 图（黄色圆圈=信号K线）</p>")
                lines.append(ch["svg_1h"])
            if ch.get("svg_1d"):
                lines.append(f"<p>日线图</p>")
                lines.append(ch["svg_1d"])
    lines.append("</body></html>")
    return "\n".join(lines)

# === 主流程 ===
def main():
    print(f"=== Gate.io 骨架K扫描 ===  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    # 1. 获取 Top160 合约
    contracts = get_top_contracts(TOP_N)
    if not contracts:
        notify_pushplus("Gate.io扫描：失败", "<p>无法获取合约列表</p>")
        return

    # 2. 扫描
    print(f"\n开始扫描 {len(contracts)} 个合约...")
    up_hits, down_hits = scan_contracts(contracts)
    total = len(up_hits) + len(down_hits)
    print(f"\n命中: 上轨{len(up_hits)} + 下轨{len(down_hits)} = {total}")

    # 3. 高质量信号生成 SVG 图表
    hq_up = [h for h in up_hits if h["batr"] > 1.5 and h["pct_above_band"] > 1.0]
    hq_down = [h for h in down_hits if h["batr"] > 1.5 and h["pct_above_band"] > 1.0]
    all_hq = hq_up + hq_down
    charts = []

    if all_hq:
        print(f"\n为 {len(all_hq)} 个高质量信号生成图表...")
    for h in all_hq:
        try:
            contract = h["contract"]
            # 1h K线图（含BOLL + 信号标记）
            klines_1h = fetch_klines(contract, "1h", KLIMIT)
            compute_indicators(klines_1h)
            # 找到信号K线的索引（在最后 LOOKBACK 根中）
            signal_idx = None
            for i in range(len(klines_1h) - 1, max(len(klines_1h) - LOOKBACK - 1, -1), -1):
                k = klines_1h[i]
                if h["signal"] == "up" and k.get("skel_up"):
                    signal_idx = i
                    break
                if h["signal"] == "down" and k.get("skel_down"):
                    signal_idx = i
                    break
            if signal_idx is not None:
                signal_idx = signal_idx - (len(klines_1h) - CHART_CANDLES)
                if signal_idx < 0:
                    signal_idx = None

            chart_data = klines_1h[-CHART_CANDLES:] if len(klines_1h) > CHART_CANDLES else klines_1h
            display_idx = signal_idx
            if display_idx is not None:
                offset = max(0, len(klines_1h) - CHART_CANDLES)
                display_idx = display_idx - offset
                if display_idx < 0:
                    display_idx = None
            svg_1h = draw_svg_chart(chart_data,
                f"{contract} 1h BOLL(26,2) {h['signal'].upper()} batr={h['batr']}",
                signal_idx=display_idx)

            # 日线图
            klines_1d = fetch_klines(contract, "1d", DKLIMIT)
            compute_indicators(klines_1d)
            dchart = klines_1d[-CHART_CANDLES:] if len(klines_1d) > CHART_CANDLES else klines_1d
            svg_1d = draw_svg_chart(dchart,
                f"{contract} 1d BOLL(26,2)",
                signal_idx=len(dchart) - 1 if dchart else None)

            charts.append({"contract": contract, "signal": h["signal"], "vol_24h": h["vol_24h"], "svg_1h": svg_1h, "svg_1d": svg_1d})
            print(f"  {contract} ✓")
        except Exception as e:
            print(f"  {contract} 图表失败: {e}")
            continue
        time.sleep(REQ_DELAY)

    # 4. PushPlus 推送（纯文字表格）
    html_push = build_html(up_hits, down_hits)
    try:
        notify_pushplus("Gate.io骨架K扫描", html_push)
        print("\nPushPlus 推送成功")
    except Exception as e:
        print(f"\nPushPlus 推送失败: {e}")

    # 5. 保存完整HTML（含SVG图表，存档）
    scan_html = build_scan_html(up_hits, down_hits, charts)
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan_result.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(scan_html)
    print(f"\n完整报告已保存: {output_path}")

    # 6. 打印结果摘要
    if up_hits:
        print("\n--- 突破上轨 ---")
        for h in up_hits:
            m = " ★" if h["batr"] > 1.5 and h["pct_above_band"] > 1.0 else ""
            print(f"  {h['contract']:16s} {h['bar']:6s} batr={h['batr']:.3f} 超上轨={h['pct_above_band']:.2f}%{m}")
    if down_hits:
        print("\n--- 突破下轨 ---")
        for h in down_hits:
            m = " ★" if h["batr"] > 1.5 and h["pct_above_band"] > 1.0 else ""
            print(f"  {h['contract']:16s} {h['bar']:6s} batr={h['batr']:.3f} 破下轨={h['pct_above_band']:.2f}%{m}")

    print(f"\n=== 完成 ===")

if __name__ == "__main__":
    main()
