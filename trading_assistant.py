import time
import os
import pandas as pd
import yfinance as yf
import warnings

warnings.filterwarnings('ignore')

def check_portfolio(portfolio_csv):
    print("\n" + "="*60)
    print("MODE A: MONITOR ASET PORTFOLIO SAYA (SELL/HOLD)")
    print("="*60)
    
    if not os.path.exists(portfolio_csv):
        print(f"File {portfolio_csv} tidak ditemukan!")
        return
        
    df_port = pd.read_csv(portfolio_csv)
    
    if df_port.empty:
        print("Portfolio Anda kosong.")
        return
        
    print(f"{'TICKER':<8} | {'BELI':<6} | {'SEKARANG':<8} | {'PROFIT/LOSS':<12} | {'REKOMENDASI (AKSI)':<20}")
    print("-" * 60)
    
    for index, row in df_port.iterrows():
        ticker = row['Ticker']
        harga_beli = float(row['Harga Beli'])
        yf_ticker = f"{ticker}.JK"
        
        try:
            stock = yf.Ticker(yf_ticker)
            hist = stock.history(period="1d")
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
                
                pnl_pct = ((current_price - harga_beli) / harga_beli) * 100
                
                aksi = "HOLD"
                # Aturan Mutlak O'Neil
                if pnl_pct <= -7.0:
                    aksi = "🔴 SELL (CUT LOSS -7%)"
                elif pnl_pct >= 20.0:
                    aksi = "🟢 SELL (TAKE PROFIT 20%)"
                else:
                    if pnl_pct < 0:
                        aksi = "🟡 HOLD (Waspada)"
                    else:
                        aksi = "🟢 HOLD (Aman)"
                        
                pnl_str = f"{pnl_pct:+.2f}%"
                print(f"{ticker:<8} | {int(harga_beli):<6} | {int(current_price):<8} | {pnl_str:<12} | {aksi:<20}")
            else:
                print(f"{ticker:<8} | ERROR (Data Kosong)")
        except Exception as e:
            print(f"{ticker:<8} | ERROR: {e}")

def scan_prospects(jii_csv):
    print("\n" + "="*60)
    print("MODE B: SCAN PROSPEK INTRADAY / SWING (BUY)")
    print("="*60)
    
    df_input = pd.read_csv(jii_csv)
    
    print(f"{'TICKER':<8} | {'HARGA':<6} | {'VOLUME INTRADAY vs AVG 10D':<25}")
    print("-" * 60)
    
    found_prospect = False
    
    for index, row in df_input.iterrows():
        ticker = row['Ticker']
        yf_ticker = f"{ticker}.JK"
        
        try:
            stock = yf.Ticker(yf_ticker)
            hist = stock.history(period="1mo")
            
            if len(hist) > 10:
                current_price = hist['Close'].iloc[-1]
                current_vol = hist['Volume'].iloc[-1]
                avg_vol_10d = hist['Volume'].tail(11).head(10).mean()
                
                # Sederhana: Volume Breakout Intraday (Current Vol > 1.5x Avg Vol)
                if current_vol > (avg_vol_10d * 1.5) and current_vol > 1_000_000:
                    found_prospect = True
                    print(f"{ticker:<8} | {int(current_price):<6} | Ledakan Volume ({current_vol/avg_vol_10d:.1f}x dari Rata-rata)")
                
        except Exception:
            pass
            
    if not found_prospect:
        print("Sayang sekali, tidak ada saham dengan ledakan volume kuat saat ini.")
        print("Saran: Tahan uang cash Anda (Wait and See).")

if __name__ == "__main__":
    portfolio_file = '/Users/hanif/Saham/portfolio.csv'
    jii_file = '/Users/hanif/Saham/daftar_saham_syariah_jii_sample.csv'
    
    check_portfolio(portfolio_file)
    scan_prospects(jii_file)
    
    print("\nSelesai! Jalankan asisten ini 2 kali sehari (Sesi 1 & Sesi 2) untuk update real-time.")
