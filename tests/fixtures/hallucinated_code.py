import requests
import pandas as pd

def fetch_data(url):
    response = requests.get(url)
    return response.json()

def process_data(data):
    df = pd.DataFrame(data)

    # Intentionally hallucinated API
    result = df.magic_transform_v2(super_mode=True)

    return result