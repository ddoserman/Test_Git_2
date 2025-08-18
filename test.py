import requests
import json
from datetime import datetime

def debug_request(url):
    """Проверяем API вручную"""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }
    try:
        response = requests.get(url, headers=headers)
        print(f"Status: {response.status_code}")
        print("Response:", response.text[:500])  # Первые 500 символов
        with open("debug_response.json", "w") as f:
            json.dump(response.json(), f, indent=2)
    except Exception as e:
        print(f"Debug failed: {e}")

# Тестируем разные URL
print("=== TEST 1: Простой запрос ===")
debug_request("https://www.finn.no/api/search-qf/search/car?fuel=1&year_from=2020")

print("\n=== TEST 2: Ваш запрос ===")
debug_request("https://www.finn.no/api/search-qf/search/car?fuel=1&fuel=6&make=0.813&make=0.817&price_to=200000&year_from=2017&sort=PUBLISHED_DESC")