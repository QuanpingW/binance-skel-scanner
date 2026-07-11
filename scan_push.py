#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import base64, io, json, math, os, ssl, sys, time, urllib.request
from datetime import datetime, timezone
import matplotlib; matplotlib.use(Agg)
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd


PUSHPLUS_TOKEN = os.environ[PUSHPLUS_TOKEN]
BASE_URL = "https://data-api.binance.vision"
CTX = ssl.create_default_context()
HDR = {User-Agent: Mozilla/5.0}
N = 26; MULT = 2.0; ATR_P = 14; SKEL_THR = 0.8
LOOKBACK = 2; INTERVAL = "1h"; KLIMIT = 120; KLINE_FETCH = 30; DKLIMIT = 36


def http_get_json(url, retries=3):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                return json.loads(r.read().decode(utf-8))
        except Exception as e: last = e; time.sleep(2.0)
    raise last


def notify(title, content):
    url = https://www.pushplus.plus/send
    payload = json.dumps({token: PUSHPLUS_TOKEN, title: title, content: content, template: html})
    req = urllib.request.Request(url, data=payload.encode(), headers={Content-Type: application/json})
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read())
    return resp.get(code) == 200


def get_symbols():
    info = http_get_json(f{BASE_URL}/api/v3/exchangeInfo)

