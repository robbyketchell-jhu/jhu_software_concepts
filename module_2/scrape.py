import urllib3

URL = 'https://www.thegradcafe.com/survey'

resp = urllib3.request("GET", URL)

print(resp.data)
