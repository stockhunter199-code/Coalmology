import os
import json
import time
import pandas as pd
import numpy as np
import yfinance as yf
import pandas_ta as ta

# Mengatur path dinamis agar selalu mengarah ke folder py-engine tempat skrip berada
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TICKER_JSON_PATH = os.path.join(BASE_DIR, "ticker.json")
OUTPUT_HTML_PATH = os.path.join(BASE_DIR, "..", "index.html") # Taruh di luar py-engine

def load_tickers_with_retry(max_retries=5, delay=2):
    """Membaca file json dengan mekanisme pengulangan jika gagal."""
    for attempt in range(1, max_retries + 1):
        try:
            with open(TICKER_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"✅ Sukses membaca ticker.json pada percobaan ke-{attempt}")
                return data
        except (ConfigFileError, json.JSONDecodeError, IOError) as e:
            print(f"⚠️ [Percobaan {attempt}/{max_retries}] Gagal membaca ticker.json: {e}")
            if attempt < max_retries:
                time.sleep(delay)
            else:
                print("❌ Batas percobaan habis. Gagal memuat konfigurasi ticker.")
                raise e

def get_macro_filter(futures_ticker):
    """Memeriksa tren batubara global (Newcastle). Wajib di atas MA50 dan MA200."""
    try:
        coal = yf.Ticker(futures_ticker)
        df = coal.history(period="1y")
        if df.empty:
            return False, 0.0
        
        df['MA50'] = ta.sma(df['Close'], length=50)
        df['MA200'] = ta.sma(df['Close'], length=200)
        
        last_close = df['Close'].iloc[-1]
        last_ma50 = df['MA50'].iloc[-1]
        last_ma200 = df['MA200'].iloc[-1]
        
        is_bullish = last_close > last_ma50 and last_close > last_ma200
        return is_bullish, last_close
    except Exception as e:
        print(f"Gagal mengambil data macro filter: {e}")
        return False, 0.0

def analyze_stock(ticker):
    """Menerapkan logika screening teknikal untuk setiap saham."""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")
        if df.empty or len(df) < 50:
            return None
        
        df['MA20'] = ta.sma(df['Close'], length=20)
        df['Vol_MA20'] = ta.sma(df['Volume'], length=20)
        
        bb = ta.bbands(df['Close'], length=20, std=2)
        df['BB_Upper'] = bb['BBU_20_2.0']
        df['BB_Lower'] = bb['BBL_20_2.0']
        df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['MA20']
        
        is_squeeze = df['BB_Width'].iloc[-1] < ta.sma(df['BB_Width'], length=20).iloc[-1]
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        recent_df = df.iloc[-20:]
        resistance = recent_df['High'].max()
        support = recent_df['Low'].min()
        
        price = current['Close']
        volume = current['Volume']
        vol_ma = current['Vol_MA20']
        atr = current['ATR']
        
        vol_spike = volume > (1.5 * vol_ma)
        price_breakout = price >= prev['BB_Upper'] or price >= resistance
        in_buy_zone = support <= price <= (support * 1.03)
        
        status = "HOLD / WATCHING"
        action_trigger = "None"
        
        if price_breakout and vol_spike:
            status = "STRONG BUY (Breakout)"
            action_trigger = "Breakout Resistance + Vol Spike"
        elif in_buy_zone and is_squeeze:
            status = "BUY ON WEAKNESS"
            action_trigger = "Accumulation Near Support + BB Squeeze"
            
        stop_loss = support - (1.5 * atr) if not np.isnan(atr) else price * 0.95
        risk = price - stop_loss
        target_price = price + (3 * risk)
        potential_upside = ((target_price - price) / price) * 100
        
        return {
            "Ticker": ticker.replace(".JK", ""),
            "Price": int(price),
            "Status": status,
            "Trigger": action_trigger,
            "Support": int(support),
            "Resistance": int(resistance),
            "Stop_Loss": int(stop_loss),
            "Target": int(target_price),
            "Upside": f"{potential_upside:.1f}%",
            "Vol_Ratio": f"{(volume/vol_ma):.2f}x"
        }
    except Exception as e:
        print(f"Error memproses {ticker}: {e}")
        return None

def generate_html_dashboard(macro_status, coal_price, results):
    """Membuat dasbor web statis dan menyimpannya di luar folder py-engine."""
    macro_badge = "<span class='badge bg-success'>BULLISH</span>" if macro_status else "<span class='badge bg-danger'>BEARISH (No Trade Zone)</span>"
    
    rows = ""
    for r in results:
        status_class = "table-success text-dark font-weight-bold" if "BUY" in r['Status'] else ""
        rows += f"""
        <tr class="{status_class}">
            <td><strong>{r['Ticker']}</strong></td>
            <td>Rp {r['Price']:,}</td>
            <td><span class="badge {'bg-primary' if 'BUY' in r['Status'] else 'bg-secondary'}">{r['Status']}</span></td>
            <td>{r['Trigger']}</td>
            <td>Rp {r['Support']:,}</td>
            <td>Rp {r['Resistance']:,}</td>
            <td class="text-danger">Rp {r['Stop_Loss']:,}</td>
            <td class="text-success">Rp {r['Target']:,} ({r['Upside']})</td>
            <td>{r['Vol_Ratio']}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Screener Saham Batubara Otomatis</title>
        <link href="https://jsdelivr.net" rel="stylesheet">
        <style> body {{ padding: 20px; background-color: #f8f9fa; }} </style>
    </head>
    <body>
        <div class="container">
            <h1 class="mb-4">⛏️ Coal Stock Screener Dashboard</h1>
            <div class="card mb-4">
                <div class="card-body">
                    <h5 class="card-title">Macro Market Condition Filter</h5>
                    <p class="card-text">Newcastle Coal Futures: <strong>${coal_price:.2f}</strong> | Status: {macro_badge}</p>
                    <small class="text-muted">Jika Bearish, disarankan membatasi porsi atau wait and see demi menjaga winrate.</small>
                </div>
            </div>
            
            <h3 class="mb-3">Sinyal Saham Batubara Hari Ini</h3>
            <div class="table-responsive">
                <table class="table table-bordered table-striped align-middle">
                    <thead class="table-dark">
                        <tr>
                            <th>Ticker</th>
                            <th>Harga Terakhir</th>
                            <th>Status</th>
                            <th>Trigger Sinyal</th>
                            <th>Support (20D)</th>
                            <th>Resistance (20D)</th>
                            <th>Stop Loss (ATR)</th>
                            <th>Target Jual (1:3)</th>
                            <th>Rasio Vol</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>
            </div>
            <footer class="mt-5 text-muted text-center"><small>Diperbarui otomatis via GitHub Actions setiap sore setelah pasar tutup.</small></footer>
        </div>
    </body>
    </html>
    """
    # Menulis ke file diluar folder py-engine (OUTPUT_HTML_PATH)
    with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)

def main():
    print("Memuat file konfigurasi ticker...")
    config = load_tickers_with_retry()
    
    print("Memulai analisa macro market...")
    macro_bullish, coal_price = get_macro_filter(config["macro_futures_ticker"])
    
    results = []
    for ticker in config["stock_tickers"]:
        print(f"Memproses analisa teknikal untuk: {ticker}")
        stock_data = analyze_stock(ticker)
        if stock_data:
            results.append(stock_data)
            
    print(f"Menghasilkan dashboard statis di {OUTPUT_HTML_PATH}...")
    generate_html_dashboard(macro_bullish, coal_price, results)
    print("Proses skrining selesai sukses!")

if __name__ == "__main__":
    main()
