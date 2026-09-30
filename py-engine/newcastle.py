import requests
import pandas as pd

def fetch_newcastle_data():
    """
    Mengambil data harga Newcastle Coal Futures dengan URL API yang dipecah per bagian.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://investing.com"
    }
    
    # --- KITA PECAH URL API MENJADI BEBERAPA BAGIAN DI SINI ---
    base_url = "https://investing.com"
    commodity_id = "959211"            # ID internal untuk Newcastle Coal Futures
    endpoint = "getchartdata"          # Aksi untuk mengambil data grafik/historis
    period = "P1Y"                     # P1Y = Period 1 Year (Data 1 tahun terakhir untuk SMA)
    interval = "P1D"                   # P1D = Period 1 Day (Data harian)
    
    # Menggabungkan seluruh bagian menjadi satu URL utuh secara otomatis
    url = f"{base_url}/{commodity_id}/{endpoint}?period={period}&interval={interval}"
    
    try:
        print(f"🔄 Menghubungi API: {base_url}/{commodity_id}/...")
        response = requests.get(url, headers=headers, timeout=15)
        json_data = response.json()
        
        # Ekstrak data lilin [[Timestamp, Open, High, Low, Close]]
        raw_candles = json_data["data"]
        
        # Konversi ke tabel DataFrame Pandas
        df = pd.DataFrame(raw_candles, columns=["Timestamp", "Open", "High", "Low", "Close"])
        df["Close"] = df["Close"].astype(float)
        
        # Ambil harga terakhir di baris paling bawah
        harga_terakhir = df["Close"].iloc[-1]
        
        print(f"✅ Sukses! Harga Newcastle saat ini: ${harga_terakhir}")
        return df, harga_terakhir
        
    except Exception as e:
        print(f"⚠️ Gagal mengambil data: {e}. Menggunakan harga jaring pengaman.")
        df_kosong = pd.DataFrame(columns=["Close"])
        return df_kosong, 145.0
