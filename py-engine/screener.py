import os
import json
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import pandas_ta as ta

# Mengatur path dinamis agar selalu mengarah ke folder py-engine tempat skrip berada
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TICKER_JSON_PATH = os.path.join(BASE_DIR, "ticker.json")
OUTPUT_HTML_PATH = os.path.join(BASE_DIR, "..", "index.html")

# Mengambil API Key dari Environment Variable GitHub Secrets
API_KEY = os.getenv("ALPHA_VANTAGE_KEY", "DEMO")

def load_tickers_with_retry(max_retries=5, delay=2):
    """Membaca file json dengan mekanisme pengulangan jika gagal."""
    for attempt in range(1, max_retries + 1):
        try:
            with open(TICKER_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"✅ Sukses membaca ticker.json pada percobaan ke-{attempt}")
                return data
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ [Percobaan {attempt}/{max_retries}] Gagal membaca ticker.json: {e}")
            if attempt < max_retries:
                time.sleep(delay)
            else:
                print("❌ Batas percobaan habis. Gagal memuat konfigurasi ticker.")
                raise e
def get_stock_sentiment(ticker):
    """
    Mengambil sentimen berita dari Alpha Vantage (Fungsi NEWS_SENTIMENT).
    Menghasilkan label: BULLISH, BEARISH, atau NEUTRAL beserta skor rata-ratanya.
    """
    clean_ticker = ticker.replace(".JK", "")
    url = f"https://alphavantage.co{clean_ticker}&apikey={API_KEY}"
    
    try:
        # Pembatasan jeda 15 detik demi kepatuhan Free Tier rate limit Alpha Vantage (maks 5 call/menit)
        time.sleep(15) 
        
        response = requests.get(url, timeout=15)
        data = response.json()
        
        if "feed" not in data or not data["feed"]:
            return "NEUTRAL (Wajar)", 0.0
        
        total_sentiment = 0.0
        count = 0
        
        for article in data["feed"]:
            for ticker_sentiment in article.get("ticker_sentiment", []):
                if ticker_sentiment["ticker"] == clean_ticker:
                    total_sentiment += float(ticker_sentiment["ticker_sentiment_score"])
                    count += 1
        
        if count == 0:
            return "NEUTRAL (Wajar)", 0.0
            
        avg_score = total_sentiment / count
        
        if avg_score >= 0.15:
            return "BULLISH (Positif)", avg_score
        elif avg_score <= -0.15:
            return "BEARISH (Negatif)", avg_score
        else:
            return "NEUTRAL (Wajar)", avg_score
            
    except Exception as e:
        print(f"Gagal memproses analisis sentimen untuk {clean_ticker}: {e}")
        return "ERROR API", 0.0

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

def analyze_stock(ticker, news_status):
    """
    Logika screening: Mengizinkan Breakout Volume tinggi untuk Lapis 1,
    atau mencicil secara aman (Buy on Weakness) pada saham murah yang sedang sepi.
    """
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="1y")
        if df.empty or len(df) < 50:
            return None
        
        # Ambil indikator Fundamental dasar untuk mengamankan posisi cicil
        info = stock.info
        trailing_pe = info.get("trailingPE", 0)
        pbv = info.get("priceToBook", 0)
        
        # Filter valuasi standar aman (PER < 8x atau PBV < 1.2x dianggap murah di batubara)
        is_undervalued = (trailing_pe > 0 and trailing_pe < 8) or (pbv > 0 and pbv < 1.2)
        
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
        
        # Area Beli Cicil: Harga berada maksimal 3% di sekitar garis support bawah
        in_buy_zone = support <= price <= (support * 1.03) or price <= (current['MA20'] * 0.98)
        
        status = "HOLD / WATCHING"
        action_trigger = "None"
        
        if "BEARISH" not in news_status:
            if price_breakout and vol_spike:
                status = "STRONG BUY (Breakout)"
                action_trigger = "Institusi Masuk: Breakout Resistance + Volume Spike"
            elif in_buy_zone and is_squeeze and is_undervalued:
                # KONDISI KHUSUS: Walau volume sepi, tetap lolos beli untuk tipe INVESTASI CICIL
                status = "BUY ON WEAKNESS (Cicil)"
                action_trigger = "Siklus Akumulasi: Saham Murah + Sepi di Area Support Jangka Panjang"
        else:
            status = "AVOID (Bad News)"
            action_trigger = "Sinyal Dibatalkan Akibat Sentimen Negatif Berita"
            
        stop_loss = support - (1.5 * atr) if not np.isnan(atr) else price * 0.92
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
            "Vol_Ratio": f"{(volume/vol_ma):.2f}x",
            "Sentiment": news_status
        }
    except Exception as e:
        print(f"Error memproses {ticker}: {e}")
        return None

def generate_html_dashboard(macro_status, coal_price, results):
    """Membuat dasbor web statis menggunakan stylesheet CSS lokal."""
    macro_badge = "<span class='badge bg-success'>BULLISH</span>" if macro_status else "<span class='badge bg-danger'>BEARISH (No Trade Zone)</span>"
    
    rows = ""
    for r in results:
        # Menentukan kelas warna baris tabel
        if "STRONG BUY" in r['Status'] or "BUY ON WEAKNESS" in r['Status']:
            status_class = "row-buy"
        elif "AVOID" in r['Status']:
            status_class = "row-avoid"
        else:
            status_class = ""
            
        # Menentukan warna lencana sentimen
        if "BULLISH" in r['Sentiment']:
            sent_badge = f"<span class='badge bg-success'>{r['Sentiment']}</span>"
        elif "BEARISH" in r['Sentiment']:
            sent_badge = f"<span class='badge bg-danger'>{r['Sentiment']}</span>"
        else:
            sent_badge = f"<span class='badge bg-secondary'>{r['Sentiment']}</span>"

        rows += f"""
        <tr class="{status_class}">
            <td><strong>{r['Ticker']}</strong></td>
            <td>Rp {r['Price']:,}</td>
            <td><span class="badge {'bg-primary' if 'BUY' in r['Status'] else ('bg-danger' if 'AVOID' in r['Status'] else 'bg-secondary')}">{r['Status']}</span></td>
            <td>{sent_badge}</td>
            <td><small>{r['Trigger']}</small></td>
            <td>Rp {r['Support']:,}</td>
            <td>Rp {r['Resistance']:,}</td>
            <td class="text-danger">Rp {r['Stop_Loss']:,}</td>
            <td class="text-success">Rp {r['Target']:,} ({r['Upside']})</td>
            <td>{r['Vol_Ratio']}</td>
        </tr>
        """

    # Memanggil stylesheet lokal dari folder assets/style.css
    html_content = f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Screener Saham Batubara Otomatis</title>
        <link rel="stylesheet" href="./assets/style.css">
    </head>
    <body>
        <div class="container">
            <h1>⛏️ Premium Coal Stock Screener</h1>
            <div class="card">
                <h5 class="card-title">Filter Makro Komoditas Global</h5>
                <p>Newcastle Coal Futures: <strong>${coal_price:.2f}</strong> | Tren: {macro_badge}</p>
                <span class="text-muted">Sistem memadukan parameter Teknikal Aksi Harga + Analisis Sentimen NLP.</span>
            </div>
            
            <h3>Kombinasi Sinyal & Sentimen Lapis 1 & 2</h3>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>Ticker</th>
                            <th>Harga Last</th>
                            <th>Status Eksekusi</th>
                            <th>Sentimen Pasar (AI)</th>
                            <th>Pemicu Sinyal</th>
                            <th>Support</th>
                            <th>Resistance</th>
                            <th>Stop Loss</th>
                            <th>Target Profit (1:3)</th>
                            <th>Rasio Vol</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>
            </div>
            <footer><span class="text-muted">Pembaruan terjadwal otomatis di cloud setiap sore hari setelah penutupan IHSG.</span></footer>
        </div>
    </body>
    </html>
    """
    with open(OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_content)

def main():
    print("Memuat berkas konfigurasi...")
    config = load_tickers_with_retry()
    
    print("Memulai analisa macro market...")
    macro_bullish, coal_price = get_macro_filter(config["macro_futures_ticker"])
    
    results = []
    for ticker in config["stock_tickers"]:
        print(f"--- Memproses {ticker} ---")
        print(f"Mengambil data sentimen berita Alpha Vantage...")
        news_status, _ = get_stock_sentiment(ticker)
        
        print(f"Mengevaluasi pola harga teknikal...")
        stock_data = analyze_stock(ticker, news_status)
        if stock_data:
            results.append(stock_data)
            
    print(f"Memperbarui visual berkas dasbor di {OUTPUT_HTML_PATH}...")
    generate_html_dashboard(macro_bullish, coal_price, results)
    print("🚀 Seluruh proses penyaringan selesai dengan sukses!")

if __name__ == "__main__":
    main()
