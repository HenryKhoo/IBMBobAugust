"""One-off diagnostic: list Granite (and other) generative model ids available
per watsonx.ai region for this account's API key.

Unlike the project-scoped calls in `check_watsonx.py`, GET
/ml/v1/foundation_model_specs is account/region level and does not require
a project_id or an associated WML instance — it just needs a valid IAM
token, so it works even before you've picked which region/project to use
for generation.

Run:

    cd backend
    python -m scripts.list_watsonx_models
"""

import os

import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

REGIONS = {
    "Dallas (us-south)": "https://us-south.ml.cloud.ibm.com",
    "Frankfurt (eu-de)": "https://eu-de.ml.cloud.ibm.com",
    "London (eu-gb)": "https://eu-gb.ml.cloud.ibm.com",
}

API_VERSION = "2026-08-11"


def get_iam_token(api_key: str) -> str:
    resp = httpx.post(
        "https://iam.cloud.ibm.com/identity/token",
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def list_model_ids(base_url: str, token: str) -> list[str]:
    resp = httpx.get(
        f"{base_url}/ml/v1/foundation_model_specs",
        params={"version": API_VERSION, "limit": 200},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return [m["model_id"] for m in resp.json().get("resources", [])]


def main() -> None:
    api_key = os.getenv("WATSONX_API_KEY", "")
    if not api_key:
        print("WATSONX_API_KEY not set in .env — nothing to check.")
        return

    token = get_iam_token(api_key)

    for label, url in REGIONS.items():
        print(f"\n=== {label} — {url} ===")
        try:
            model_ids = list_model_ids(url, token)
        except httpx.HTTPStatusError as exc:
            print(f"  FAILED — {exc.response.status_code}: {exc.response.text[:200]}")
            continue

        granite_chat = sorted(
            m
            for m in model_ids
            if "granite" in m
            and "embedding" not in m
            and "ttm" not in m
            and "guardian" not in m
        )
        if granite_chat:
            print(f"  Granite generation models available ({len(granite_chat)}):")
            for m in granite_chat:
                print(f"    - {m}")
        else:
            print("  No Granite generation models in this region's catalog.")


if __name__ == "__main__":
    main()
