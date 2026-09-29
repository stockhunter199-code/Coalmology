import os
import json
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import talib # Menggunakan Gold Standard Library Finansial Modern

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TICKER_JSON_PATH = os.path.join(BASE_DIR, "ticker.json")
OUTPUT_HTML_PATH = os.path.join(BASE_DIR, "..", "index.html")

API_KEY = os.getenv("ALPHA_VANTAGE_KEY", "DEMO")

def load_tickers_with_retry(max_retries=5, delay=2):
    """Membaca file json dengan mekanisme pengulangan jika gagal."""
    for attempt in range(1, max_retries + 1):
        try:
            with open(TICKER_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ [Percobaan {attempt}/{max_retries}] Gagal membaca ticker.json: {e}")
            if attempt < max_retries:
                time.sleep(delay)
            else:
                raise e

def get_stock_sentiment(ticker):
    """Mengambil sentimen berita dari Alpha Vantage."""
    clean_ticker = ticker.replace(".JK", "")
    url = f"https://alphavantage.co{clean_ticker}&apikey={API_KEY}"
    try:
        time.sleep(15) 
        response = requests.get(url, timeout=15)
        data = response.json()
        if "feed" not in data or not data["feed"]:
            return "NEUTRAL", 0.0
        total_sentiment, count = 0.0, 0
        for article in data["feed"]:
            for t_sent in article.get("ticker_sentiment", []):
                if t_sent["ticker"] == clean_ticker:
                    total_sentiment += float(t_sent["ticker_sentiment_score"])
                    count += 1
        if count == 0: return "NEUTRAL", 0.0
        avg_score = total_sentiment / count
        if avg_score >= 0.15: return "BULLISH", avg_score
        elif avg_score <= -0.15: return "BEARISH", avg_score
        else: return "NEUTRAL", avg_score
    except Exception as e:
        print(f"Gagal memproses analisis sentimen untuk {clean_ticker}: {e}")
        return "ERROR API", 0.0
def get_macro_filter(futures_ticker):
    """Memeriksa tren batubara global (Newcastle) menggunakan TA-Lib SMA."""
    try:
        coal = yf.Ticker(futures_ticker)
        df = coal.history(period="1y")
        if df.empty or len(df) < 200: return False, 0.0
        
        # Kalkulasi presisi tinggi menggunakan C-extension TA-Lib
        ma50 = talib.SMA(df['Close'].values, timeperiod=50)
        ma200 = talib.SMA(df['Close'].values, timeperiod=200)
        
        return df['Close'].iloc[-1] > ma50[-1] and df['Close'].iloc[-1] > ma200[-1], df['Close'].iloc[-1]
    except Exception as e:
        return False, 0.0

def process_screener(ticker, news_status, strategy_type):
    """Memproses skrining presisi tinggi menggunakan TA-Lib."""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")
        if df.empty or len(df) < 50: return None
        
        info = stock.info
        pe_ratio = info.get("trailingPE", 0)
        pbv_ratio = info.get("priceToBook", 0)
        div_yield = info.get("dividendYield", 0) * 100 if info.get("dividendYield") else 0.0
        
        close_prices = df['Close'].values
        volume_data = df['Volume'].values.astype(float)
        
        # Pemanggilan fungsi indikator bawaan TA-Lib secara langsung
        ma20 = talib.SMA(close_prices, timeperiod=20)
        vol_ma20 = talib.SMA(volume_data, timeperiod=20)
        upperband, middleband, lowerband = talib.BBANDS(close_prices, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
        atr_data = talib.ATR(df['High'].values, df['Low'].values, close_prices, timeperiod=14)
        
        bb_width = (upperband - lowerband) / ma20
        bb_width_ma = talib.SMA(bb_width, timeperiod=20)
        
        price = df['Close'].iloc[-1]
        prev_upper = upperband[-2]
        volume = df['Volume'].iloc[-1]
        vol_ma = vol_ma20[-1]
        atr = atr_data[-1]
        
        recent_df = df.iloc[-20:]
        resistance, support = recent_df['High'].max(), recent_df['Low'].min()
        
        vol_spike = volume > (1.5 * vol_ma)
        price_breakout = price >= prev_upper or price >= resistance
        in_buy_zone = support <= price <= (support * 1.03)
        is_squeeze = bb_width[-1] < bb_width_ma[-1]
        
        status, action_trigger = "WAIT AND SEE", "Belum Ada Momentum Tren Klasik"
        
        if "BEARISH" in news_status:
            status, action_trigger = "AVOID (Bad News)", "Dibatalkan Sentimen Negatif Berita Pasar"
        else:
            if strategy_type == "swing":
                if price_breakout and vol_spike:
                    status = "STRONG BUY (Breakout)"
                    action_trigger = "Breakout Resistance Valid + Lonjakan Volume TA-Lib Terkonfirmasi"
                else:
                    status = "WAIT AND SEE"
                    action_trigger = "Harga Sideways Konsolidasi, Tunggu Breakout Volume"
            elif strategy_type == "value":
                is_cheap = (0 < pe_ratio < 8) or (0 < pbv_ratio < 1.2)
                if in_buy_zone and is_squeeze and is_cheap:
                    status = "ACCUMULATION (Cicil)"
                    action_trigger = "Siklus Akumulasi Bawah: Emiten Murah Fundamental Kokoh"
                else:
                    status = "HOLD / WATCHING"
                    action_trigger = "Valuasi Premium atau Harga Menjauhi Area Support Kuat"

        stop_loss = support - (1.5 * atr) if not np.isnan(atr) else price * 0.92
        target_price = price + (3 * (price - stop_loss))
        upside = ((target_price - price) / price) * 100
        
        return {
            "Ticker": ticker.replace(".JK", ""), "Price": int(price), "Status": status,
            "Trigger": action_trigger, "Support": int(support), "Resistance": int(resistance),
            "Stop_Loss": int(stop_loss), "Target": int(target_price), "Upside": f"{upside:.1f}%",
            "Vol_Ratio": f"{(volume/vol_ma):.2f}x", "Sentiment": news_status,
            "PE": f"{pe_ratio:.1f}x" if pe_ratio else "-", "DY": f"{div_yield:.1f}%"
        }
    except Exception as e:
        print(f"Error memproses {ticker}: {e}")
        return None
def generate_html_dashboard(macro_status, coal_price, swing_results, value_results):
    """Membuat dasbor web statis dengan filter Javascript interaktif bawaan."""
    macro_badge = "<span class='badge bg-success'>BULLISH</span>" if macro_status else "<span class='badge bg-danger'>BEARISH (No Trade Zone)</span>"
    
    def build_rows(results):
        html = ""
        for r in results:
            row_cls = "row-buy" if "STRONG BUY" in r['Status'] or "ACCUMULATION" in r['Status'] else ("row-avoid" if "AVOID" in r['Status'] else "")
            sent_badge = f"<span class='badge bg-success'>{r['Sentiment']}</span>" if "BULLISH" in r['Sentiment'] else (f"<span class='badge bg-danger'>{r['Sentiment']}</span>" if "BEARISH" in r['Sentiment'] else f"<span class='badge bg-secondary'>{r['Sentiment']}</span>")
            status_badge = "bg-primary" if "BUY" in r['Status'] or "ACCUM" in r['Status'] else ("bg-danger" if "AVOID" in r['Status'] else "bg-secondary")

            html += f"""
            <tr class="{row_cls}">
                <td><strong>{r['Ticker']}</strong></td>
                <td>Rp {r['Price']:,}</td>
                <td><span class="badge {status_badge}">{r['Status']}</span></td>
                <td>{sent_badge}</td>
                <td><small>{r['Trigger']}</small></td>
                <td>{r['PE']} | {r['DY']}</td>
                <td>Rp {r['Support']:,} / Rp {r['Resistance']:,}</td>
                <td class="text-danger">Rp {r['Stop_Loss']:,}</td>
                <td class="text-success">Rp {r['Target']:,} ({r['Upside']})</td>
                <td>{r['Vol_Ratio']}</td>
            </tr>
            """
        return html

    html_content = f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Screener Saham Batubara Multi-Strategi TA-Lib</title>
        <link rel="stylesheet" href="./assets/style.css">
        <style>
            .filter-btn-container {{ margin-bottom: 20px; display: flex; gap: 10px; }}
            .btn {{ padding: 10px 20px; font-weight: bold; border-radius: 6px; cursor: pointer; border: 1px solid #ccc; background: #fff; }}
            .btn.active {{ background: #1f2937; color: #fff; border-color: #1f2937; }}
            .strategy-table {{ display: none; }}
            .strategy-table.active-table {{ display: table; width:100%; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>⛏️ Premium Coal Stock Screener (Powered by TA-Lib)</h1>
            <div class="card">
                <h5 class="card-title">Filter Makro Komoditas Global</h5>
                <p>Newcastle Coal Futures: <strong>${coal_price:.2f}</strong> | Tren: {macro_badge}</p>
                <span class="text-muted">Sistem memadukan parameter Teknikal C-Extension TA-Lib + Sentimen Berita NLP.</span>
            </div>
            
            <div class="filter-btn-container">
                <button id="btn-swing" class="btn active" onclick="switchStrategy('swing')">📈 Strategi Murni Swing</button>
                <button id="btn-value" class="btn" onclick="switchStrategy('value')">💎 Strategi Value Investing</button>
            </div>
            
            <h3 id="strategy-title">Kombinasi Sinyal Murni Swing (Fokus Momentum)</h3>
            <div class="table-responsive">
                <table id="table-swing" class="strategy-table active-table">
                    <thead>
                        <tr>
                            <th>Ticker</th><th>Harga Last</th><th>Status</th><th>Sentimen</th><th>Pemicu Sinyal</th><th>PER | DY</th><th>Support/Res</th><th>Stop Loss</th><th>Target Profit</th><th>Vol Ratio</th>
                        </tr>
                    </thead>
                    <tbody>{build_rows(swing_results)}</tbody>
                </table>
                <table id="table-value" class="strategy-table">
                    <thead>
                        <tr>
                            <th>Ticker</th><th>Harga Last</th><th>Status</th><th>Sentimen</th><th>Pemicu Sinyal</th><th>PER | DY</th><th>Support/Res</th><th>Stop Loss</th><th>Target Profit</th><th>Vol Ratio</th>
                        </tr>
                    </thead>
                    <tbody>{build_rows(value_results)}</tbody>
                </table>
            </div>
            <footer><span class="text-muted">Pembaruan terjadwal otomatis di cloud setiap sore hari setelah penutupan IHSG.</span></footer>
        </div>
        <script>
            function switchStrategy(strat) {{
                document.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.strategy-table').forEach(t => t.classList.remove('active-table'));
                if(strat === 'swing') {{
                    document.getElementById('btn-swing').classList.add('active');
                    document.getElementById('table-swing').classList.add('active-table');
                    document.getElementById('strategy-title').innerText = "Kombinasi Sinyal Murni Swing (Fokus Momentum)";
                }} else {{
                    document.getElementById('btn-value').classList.add('active');
                    document.getElementById('table-value').classList.add('active-table');
                    document.getElementById('strategy-title').innerText = "Kombinasi Sinyal Value Investing (Fokus Akumulasi Murah)";
                }}
            }}
        </script>
    </body>
    </html>
    """
    with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)

def main():
    print("Memuat konfigurasi ticker...")
    config = load_tickers_with_retry()
    macro_bullish, coal_price = get_macro_filter(config["macro_futures_ticker"])
    
    swing_results, value_results = [], []
    for ticker in config["stock_tickers"]:
        print(f"--- Memproses Sentimen Pasar: {ticker} ---")
        news_status, _ = get_stock_sentiment(ticker)
        
        swing_data = process_screener(ticker, news_status, "swing")
        value_data = process_screener(ticker, news_status, "value")
        
        if swing_data: swing_results.append(swing_data)
        if value_data: value_results.append(value_data)
            
    print("Mengekspor visual halaman dasbor multi-strategi...")
    generate_html_dashboard(macro_bullish, coal_price, swing_results, value_results)
    print("🚀 Sistem berkecepatan tinggi TA-Lib sukses diperbarui!")

if __name__ == "__main__":
    main()
