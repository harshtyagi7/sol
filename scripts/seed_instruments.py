"""
Download and cache NSE/BSE instrument master from Kite.
Run this script once daily before market open.

Usage: python -m scripts.seed_instruments
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


async def main():
    from sol.broker.kite_client import get_kite_client
    from sol.config import get_settings

    settings = get_settings()
    if not settings.KITE_API_KEY:
        print("KITE_API_KEY not configured. Skipping instrument download.")
        return

    client = get_kite_client()
    if not client.is_authenticated():
        print("Kite not authenticated. Please login first via /api/auth/login")
        return

    print("Downloading NSE instruments...")
    instruments = client.get_instruments("NSE")
    print(f"Downloaded {len(instruments)} NSE instruments")

    # Save to file for reference
    import json
    with open("nse_instruments.json", "w") as f:
        json.dump(instruments[:100], f, indent=2, default=str)  # Save first 100 as sample

    print("Done! Instruments saved to nse_instruments.json")


if __name__ == "__main__":
    asyncio.run(main())
