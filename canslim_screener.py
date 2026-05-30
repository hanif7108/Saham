import yfinance as yf
from tradingview_ta import TA_Handler, Interval
import pandas as pd
import os

def get_tv_market_direction():
    print("Mengecek Arah Pasar (Market Direction - IHSG) dari TradingView...")
    try:
        ihsg = TA_Handler(
            symbol="COMPOSITE",
            exchange="IDX",
            screener="indonesia",
            interval=Interval.INTERVAL_1_DAY
        )
        analysis = ihsg.get_analysis()
        close = analysis.indicators.get("close", 0)
        sma50 = analysis.indicators.get("SMA50", 0)
        
        if close > sma50:
            print(f"Status IHSG: UPTREND (Harga: {close:.2f} > SMA50: {sma50:.2f})")
            return "Uptrend"
        else:
            print(f"Status IHSG: DOWNTREND (Harga: {close:.2f} < SMA50: {sma50:.2f})")
            return "Downtrend"
    except Exception as e:
        print(f"Gagal mengambil data IHSG dari TradingView: {e}")
        return "Unknown"

def run_screener(input_csv, output_csv):
    if not os.path.exists(input_csv):
        print(f"File {input_csv} tidak ditemukan!")
        return
        
    df_input = pd.read_csv(input_csv)
    market_status = get_tv_market_direction()
    
    print("\n" + "="*60)
    print("SCREENER CAN SLIM & SHARIA MODULE (Doddy Eka Saputra)")
    print("="*60)
    
    results = []
    
    for index, row in df_input.iterrows():
        ticker = row['Ticker']
        nama = row.get('Nama Perusahaan', '')
        yf_ticker = f"{ticker}.JK"
        
        try:
            print(f"Memproses {ticker}...")
            
            # 1. TRADINGVIEW DATA (Technical)
            tv_handler = TA_Handler(
                symbol=ticker,
                exchange="IDX",
                screener="indonesia",
                interval=Interval.INTERVAL_1_DAY
            )
            tv_analysis = tv_handler.get_analysis()
            tv_ind = tv_analysis.indicators
            
            current_price = tv_ind.get("close", 0)
            high_price = tv_ind.get("high", 0)  # Daily high, but for 52W high we might need YF. 
            volume = tv_ind.get("volume", 0)
            tv_recommendation = tv_analysis.summary.get("RECOMMENDATION", "NEUTRAL")
            
            # 2. YFINANCE DATA (Fundamental)
            stock = yf.Ticker(yf_ticker)
            info = stock.info
            
            # --- EXTRACT DODDY EKA SAPUTRA MODULE METRICS ---
            
            # C: EPS QnQ > 25% (0.25)
            q_earnings_growth = info.get('earningsQuarterlyGrowth', None)
            
            # A: ROE > 17% (0.17)
            roe = info.get('returnOnEquity', None)
            
            # S: Free Float < 50%
            float_shares = info.get('floatShares', None)
            shares_out = info.get('sharesOutstanding', None)
            free_float_pct = None
            if float_shares and shares_out:
                free_float_pct = float_shares / shares_out
                
            # 6 Magic Numbers: DER, PER, PBV
            debt_to_equity = info.get('debtToEquity', None) # Usually in percentage, so < 100
            per = info.get('trailingPE', None)
            pbv = info.get('priceToBook', None)
            
            # Technical (from YF history for 52W high and avg volume)
            hist = stock.history(period="1y")
            high_52w = hist['High'].max() if not hist.empty else current_price
            avg_vol_50d = hist['Volume'].tail(50).mean() if not hist.empty else volume
            
            # --- APPLY STRICT CAN SLIM CRITERIA ---
            reasons = []
            
            # N: New Highs (Price within 15% of 52 week high)
            is_near_high = current_price >= (high_52w * 0.85) if high_52w else False
            if not is_near_high: reasons.append("Harga < 85% dari 52W High")
            
            # S: Free Float < 50%
            is_free_float_ok = True # default pass if data missing
            if free_float_pct is not None and free_float_pct >= 0.50:
                is_free_float_ok = False
                reasons.append(f"Free Float tinggi ({free_float_pct*100:.1f}%)")
                
            # C: Earning Growth > 25%
            is_growth_ok = False
            if q_earnings_growth is not None and q_earnings_growth >= 0.25:
                is_growth_ok = True
            else:
                val = f"{q_earnings_growth*100:.1f}%" if q_earnings_growth else "Kosong/Negatif"
                reasons.append(f"Laba QnQ rendah ({val})")
                
            # A: ROE > 17%
            is_roe_ok = False
            if roe is not None and roe >= 0.17:
                is_roe_ok = True
            else:
                val = f"{roe*100:.1f}%" if roe else "Kosong"
                reasons.append(f"ROE rendah ({val})")
                
            # Evaluasi Akhir
            status = "GAGAL"
            if is_near_high and is_growth_ok and is_roe_ok and is_free_float_ok:
                status = "LULUS SEMPURNA"
                
            # Format Output
            results.append({
                'Ticker': ticker,
                'Status': status,
                'Rekomendasi TV': tv_recommendation,
                'Harga': current_price,
                'Jarak 52W High': f"{((current_price / high_52w) - 1) * 100:.2f}%" if high_52w else "N/A",
                'EPS QnQ': f"{q_earnings_growth*100:.2f}%" if q_earnings_growth else "N/A",
                'ROE': f"{roe*100:.2f}%" if roe else "N/A",
                'PER': f"{per:.2f}x" if per else "N/A",
                'PBV': f"{pbv:.2f}x" if pbv else "N/A",
                'DER (%)': f"{debt_to_equity:.2f}%" if debt_to_equity else "N/A",
                'Free Float': f"{free_float_pct*100:.2f}%" if free_float_pct else "N/A",
                'Catatan Gagal': ", ".join(reasons) if reasons else "OK"
            })
            
        except Exception as e:
            print(f"  [!] Error pada {ticker}: {e}")

    # Save to CSV
    if results:
        df_results = pd.DataFrame(results)
        df_results.to_csv(output_csv, index=False)
        print("\n" + "="*60)
        print(f"Screening Selesai! Diproses {len(results)} saham.")
        print(f"Hasil lengkap (termasuk status Gagal) disimpan di: {output_csv}")
        print("="*60)

if __name__ == "__main__":
    input_file = '/Users/hanif/Saham/daftar_saham_syariah_jii_sample.csv'
    output_file = '/Users/hanif/Saham/hasil_screening_canslim.csv'
    run_screener(input_file, output_file)
