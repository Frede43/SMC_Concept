
import os

log_file = r"d:\SMC\logs\smc_bot_2026-01-13.log"
keywords = ["2181425401", "2181837722", "GBPUSDm", "USDJPYm", "Close", "SL", "TP"]

def tail_and_search(filename, n=500):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            # Read all lines
            lines = f.readlines()
            
        found_lines = []
        for line in lines:
            if "15:30" in line or "15:31" in line or "15:32" in line or "15:33" in line or "15:34" in line or "15:35" in line:
                found_lines.append(line.strip())
        
        print(f"--- LAST {n} LINES FILTERED ---")
        for l in found_lines:
            try:
                print(l)
            except UnicodeEncodeError:
                print(l.encode('ascii', 'replace').decode('ascii'))
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    tail_and_search(log_file)
