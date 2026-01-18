#!/usr/bin/env python3
"""Quick test script to verify Unsplash API integration."""

import asyncio
import logging
import sys

# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

# Add the app directory to the path
sys.path.insert(0, ".")


async def test_unsplash():
    """Test the Unsplash image service."""
    from app.config import settings
    from app.services.unsplash import (
        clear_memory_cache,
        get_image_for_destination,
        get_image_url_sync,
    )

    print("\n" + "=" * 60)
    print("UNSPLASH API TEST")
    print("=" * 60)

    # Check if API key is configured
    api_key = settings.unsplash_access_key
    print("\n1. API Key Check:")
    if api_key:
        print(f"   [OK] API key configured (length={len(api_key)}, starts with: {api_key[:8]}...)")
    else:
        print("   [FAIL] UNSPLASH_ACCESS_KEY not set!")
        return

    # Clear any existing cache
    clear_memory_cache()
    print("\n2. Cache cleared")

    # Test destinations
    test_destinations = ["Patagonia", "Paris", "Tokyo"]

    print("\n3. Testing async get_image_for_destination():")
    for dest in test_destinations:
        print(f"\n   Testing: {dest}")
        try:
            url = await get_image_for_destination(dest)
            print(f"   Result: {url[:80]}...")
            if "unsplash" in url:
                print("   [OK] Got Unsplash URL")
            elif "picsum" in url:
                print("   [WARN] Got Picsum fallback (Unsplash may have failed)")
            else:
                print("   ? Unknown URL pattern")
        except Exception as e:
            print(f"   [FAIL] Error: {e}")

    print("\n4. Testing sync get_image_url_sync() (should use cache):")
    for dest in test_destinations:
        print(f"\n   Testing: {dest}")
        try:
            url = get_image_url_sync(dest)
            print(f"   Result: {url[:80]}...")
            if "unsplash" in url:
                print("   [OK] Got Unsplash URL from cache")
            elif "picsum" in url:
                print("   [WARN] Got Picsum fallback (cache miss)")
        except Exception as e:
            print(f"   [FAIL] Error: {e}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(test_unsplash())
