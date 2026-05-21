import os
import time
import requests
from dotenv import load_dotenv
from requests.exceptions import RequestException

load_dotenv()
API_KEY = os.getenv("TABSCANNER_API_KEY")

TABSCANNER_PROCESS_URL = "https://api.tabscanner.com/api/2/process"
TABSCANNER_RESULT_URL = "https://api.tabscanner.com/api/result/"
DEFAULT_POLL_INTERVAL = 2
DEFAULT_INITIAL_WAIT = 5

def scan_receipt(image_path: str) -> dict:
    if not API_KEY:
        raise Exception("TABSCANNER_API_KEY not found in .env file.")

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file not found at: {image_path}")

    headers = {'apikey': API_KEY}

    try:
        with open(image_path, 'rb') as f:
            files = {'file': (os.path.basename(image_path), f)}
            response = requests.post(TABSCANNER_PROCESS_URL, headers=headers, files=files)

        response.raise_for_status()

        data = response.json()
        if data.get("status") == "failed" or not data.get("token"):
            raise Exception(f"Tabscanner API error on submit: {data.get('message', 'No token returned')}")

        token = data["token"]

    except RequestException as e:
        raise RequestException(f"API request failed during submission: {e}")

    time.sleep(DEFAULT_INITIAL_WAIT)
    MAX_POLLS = 30
    polls = 0
    result_url = f"{TABSCANNER_RESULT_URL}{token}"

    while polls < MAX_POLLS:
        polls += 1
        try:
            response = requests.get(result_url, headers=headers)
            response.raise_for_status()
            result_data = response.json()
            status = result_data.get("status")

            if status == "done":
                return result_data.get("result", {})
            elif status == "pending":
                time.sleep(DEFAULT_POLL_INTERVAL)
            else:
                raise Exception(f"API returned an unexpected status: {status}. Message: {result_data.get('message')}")

        except RequestException as e:
            raise RequestException(f"API request failed during polling: {e}")

    raise Exception("Receipt processing timed out after too many polling attempts.")


def parse_line_items(tabscanner_json: dict):
    items = []

    if 'lineItems' in tabscanner_json and tabscanner_json['lineItems']:
        for item in tabscanner_json['lineItems']:
            item_name_raw = item.get('descClean')
            if not item_name_raw:
                item_name_raw = item.get('desc', 'UNKNOWN')
            item_name = str(item_name_raw).strip().upper()
            item_cost = str(item.get('lineTotal', '0.00')).strip()

            if item_name.startswith('* '):
                item_name = item_name[2:]

            if item_name and item_cost != '0.00':
                items.append({
                    'Item': item_name,
                    'Cost': item_cost
                })

        return items, ""

    return [], "No line items found in the structured JSON response."