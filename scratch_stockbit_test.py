import json
import urllib.parse
from curl_cffi import requests

cookie_val = "{%22state%22:{%22access%22:{%22token%22:%22eyJhbGciOiJSUzI1NiIsImtpZCI6ImExNWQ5OGE2LTdkYzgtNDM3NS05NDk0LTEyOWJlM2RlODVkNCIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7InVzZSI6IlJhaG1uMjEiLCJlbWEiOiJzaWRxaS5yYWhtYW5AZ21haWwuY29tIiwiZnVsIjoiUmFobWFuIiwic2VzIjoiMWJWZm1wUFF3azZMUFJOdSIsImR2YyI6ImVhZDU2ZDljOWRhYWYzZmRhZjAzYWJiZTVjYjVhODFlIiwidWlkIjozNzg0NDI3LCJjb3UiOiJJRCJ9LCJleHAiOjE3ODg1Njk3MzYsImlhdCI6MTc4ODQ4MzMzNiwiaXNzIjoiU1RPQ0tCSVQiLCJqdGkiOiJiNDUzODI3MC02Yzg0LTQ1NWYtYmJiZC00MjIxNGJiYWQ2YTQiLCJuYmYiOjE3ODg0ODMzMzYsInZlciI6InYxIn0.LAmqjADKZmyn2LxPpjnNFUnYHtHQQJdadWgBuUGs2LHuuV1ycWhGiPqwgtrGYTr_fbAqFNTOFSn5Xl12cRJYWPKqNleLSydzhHunNY3a8ZDo9LqYyTRMWOXNPQMB4PZ9Pc6AhdSj4I5DzYONmShXiLldSR63KcFbNcSHsgaIoeld3tUrMqZK1_9Kbyw3QvRYvjER5ji2d6eTdRCHB5CXUINbyooILCeGc6LQ0b_sn-XR5UOOsNQRrOURfzHcPOoCMJGnhLjwF6tWWNjKl3UhYp1TwN6Bw8vShvKbecHOHwhaPrnrxwSKiM6VNVEWWTuEDfuGfVCs3PDHkWZ9DtSuIg%22%2C%22expired_at%22:%222026-09-05T00:55:36Z%22}%2C%22refresh%22:{%22token%22:%22eyJhbGciOiJSUzI1NiIsImtpZCI6ImExNWQ5OGE2LTdkYzgtNDM3NS05NDk0LTEyOWJlM2RlODVkNCIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7InR5cCI6InJlZnJlc2giLCJ1c2UiOiJSYWhtbjIxIiwiZW1hIjoic2lkcWkucmFobWFuQGdtYWlsLmNvbSIsImZ1bCI6IlJhaG1hbiIsInNlcyI6IjFiVmZtcFBRd2s2TFBSTnUiLCJkdmMiOiJlYWQ1NmQ5YzlkYWFmM2ZkYWYwM2FiYmU1Y2I1YTgxZSIsInVpZCI6Mzc4NDQyNywiY291IjoiSUQifSwiZXhwIjoxNzg5MDg4MTM2LCJpYXQiOjE3ODg0ODMzMzYsImlzcyI6IlNUT0NLQklUIiwianRpIjoiYjQ1MzgyNzAtNmM4NC00NTVmLWJiYmQtNDIyMTRiYmFkNmE0IiwibmJmIjoxNzg4NDgzMzM2LCJ2ZXIiOiJ2MSJ9.DAngtR6Yh7l_EGrpr9ImWE4ZEpoSz3IARhBzpYmVlPIwNCTVia5QN08advZVd9_OPZzKdJPKcmviVE_N4tWsNmq91dogx2cfa2CitXVDJFEwJZ-fFzj1XgpRt7PYZbOTnv3lfPdLEglJKOBoS6S3kT9uEzsNw0wm9C81KJMk2ZxvV0qTtbXGkMCU77imMB3YoC3uevTwkEgXuNmdPTFnwp5dPiLnBqrqgBdP92CmoulBvPIDJ5bfDj6xEutbXZLnUc9QUqZ3TGPovfBn-XHXeq6rJozcSAqjWk93XAEJqTBX6Vq1JESE-r3QoQfzfgVJfSkxgjHznwVxoHL1ny0KFQ%22%2C%22expired_at%22:%222026-09-11T00:55:36Z%22}%2C%22user%22:{%22id%22:3784427%2C%22username%22:%22Rahmn21%22%2C%22country%22:%22ID%22%2C%22watchlist_id%22:7181074%2C%22privilege%22:{%22code%22:0}}}%2C%22version%22:0}"
decoded = urllib.parse.unquote(cookie_val)
data = json.loads(decoded)
token = data["state"]["access"]["token"]

# Save token for later use
with open("stockbit_token.txt", "w") as f:
    f.write(token)

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Authorization': f'Bearer {token}',
    'Origin': 'https://stockbit.com',
    'Referer': 'https://stockbit.com/',
    'Accept': 'application/json, text/plain, */*'
}

# The web API might be on api.stockbit.com or stockbit.com/api
endpoints = [
    ('GET', 'https://api.stockbit.com/v2.4/broker-summary', {'symbol': 'BBCA', 'date': '2026-09-04'}),
    ('GET', 'https://api.stockbit.com/v2.4/bandarmology', {'symbol': 'BBCA'}),
    ('GET', 'https://api.stockbit.com/v2.3/bandarmology', {'symbol': 'BBCA'}),
    ('GET', 'https://api.stockbit.com/v2.2/bandarmology', {'symbol': 'BBCA'}),
    ('GET', 'https://api.stockbit.com/v2/bandarmology', {'symbol': 'BBCA'}),
    ('GET', 'https://api.stockbit.com/bandarmology/BBCA', {}),
    ('GET', 'https://api.stockbit.com/v2.4/broker-flow', {'symbol': 'BBCA'}),
    ('GET', 'https://api.stockbit.com/v2.2/broker-flow', {'symbol': 'BBCA'})
]

for method, url, params in endpoints:
    print(f"Testing {url}...")
    try:
        r = requests.request(method, url, params=params, headers=headers, impersonate='chrome')
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            print("Content:", r.text[:200])
    except Exception as e:
        print("Error:", e)
    print("-" * 40)
