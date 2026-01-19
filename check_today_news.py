
import sys
import os
from datetime import datetime
import io

# Force utf-8 for stdout/stderr
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
sys.path.append(os.getcwd())

from strategy.news_filter import NewsFilter
from loguru import logger

# Disable logger for cleaner output
logger.remove()
logger.add(sys.stderr, level="ERROR")

def main():
    print(f"Checking news for today: {datetime.now().strftime('%Y-%m-%d')}")
    
    # Config similar to settings.yaml
    config = {
        'filters': {
            'news': {
                'enabled': True,
                'mode': 'real',
                'filter_high_impact': True,
                'filter_medium_impact': True,
                'timezone_offset': 2
            }
        }
    }
    
    try:
        nf = NewsFilter(config)
        # Force refresh to ensure we get live data
        nf.force_refresh()
        nf.display_calendar()
        
    except Exception as e:
        print(f"Error checking news: {e}")

if __name__ == "__main__":
    main()
