import sys
sys.path.append("/Users/hanif/Saham/sharia_trading_ai")

import pandas as pd
from app.core import technical

def run_test():
    print("Testing Volume Profile & VIP conviction rating for ADRO...")
    try:
        res = technical.analyze_technical("ADRO")
        if not res.get("ok"):
            print(f"Error analyzing ADRO: {res.get('error')}")
            return
            
        print(f"Ticker: {res['ticker']}")
        print(f"Price: {res['price']}")
        print(f"Trend: {res['trend']}")
        
        print("\n--- Volume Profile ---")
        vp = res.get("volume_profile", {})
        print(f"POC (Point of Control): {vp.get('poc')}")
        print(f"VAL (Value Area Low): {vp.get('val')}")
        print(f"VAH (Value Area High): {vp.get('vah')}")
        print(f"Bins count: {len(vp.get('bins', []))}")
        
        print("\n--- Volatility Insight Pro ---")
        vip = res.get("volatility_insight_pro", {})
        print(f"Rating: {vip.get('rating')} / 5.0")
        print(f"Conviction: {vip.get('conviction')}")
        print("Details:")
        for detail in vip.get("details", []):
            print(f"  - {detail}")
            
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_test()
