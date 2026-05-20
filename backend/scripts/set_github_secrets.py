"""
Set GitHub Actions secrets for shreyaaassss/cadencia-magic-wallet.
Uses PyNaCl sealed-box encryption as required by GitHub API.
"""
import base64
import json
import sys
import urllib.request
import urllib.error
import os

try:
    from nacl import encoding, public
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "PyNaCl", "-q"])
    from nacl import encoding, public

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "shreyaaassss/cadencia-magic-wallet"
API = "https://api.github.com"
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
}


def gh_request(method, path, body=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()) if r.read else {}
    except urllib.error.HTTPError as e:
        content = e.read().decode()
        print(f"  HTTP {e.code} for {method} {path}: {content[:200]}")
        raise


def get_repo_public_key():
    url = f"{API}/repos/{REPO}/actions/secrets/public-key"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    box = public.SealedBox(pk)
    encrypted = box.encrypt(secret_value.encode())
    return base64.b64encode(encrypted).decode()


def set_secret(key_id: str, public_key_b64: str, name: str, value: str):
    encrypted = encrypt_secret(public_key_b64, value)
    path = f"/repos/{REPO}/actions/secrets/{name}"
    body = {"encrypted_value": encrypted, "key_id": key_id}
    url = f"{API}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=HEADERS, method="PUT")
    try:
        with urllib.request.urlopen(req) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        content = e.read().decode()
        print(f"  FAIL {name}: HTTP {e.code} — {content[:300]}")
        return False
    print(f"  OK   {name} (HTTP {status})")
    return True


# ── Read secrets ──────────────────────────────────────────────────────────────

# EC2 SSH private key
with open("cadencia-deploy.pem", "r") as f:
    ec2_key = f.read().strip()

# BACKEND_ENV_B64 — from EC2's .env.production
backend_env_b64 = (
    # paste the base64 string from: ssh ec2 "cat app/.env.production | base64 -w0"
    open("backend_env_b64.txt").read().strip()
)

secrets = {
    "EC2_HOST": "13.232.223.160",
    "EC2_USER": "ec2-user",
    "EC2_KEY": ec2_key,
    "BACKEND_ENV_B64": backend_env_b64,
}

# ── Set secrets ───────────────────────────────────────────────────────────────
print(f"Fetching public key for {REPO}...")
key_info = get_repo_public_key()
key_id = key_info["key_id"]
pub_key = key_info["key"]
print(f"  key_id={key_id}")

print("\nSetting secrets...")
ok = all(set_secret(key_id, pub_key, name, value) for name, value in secrets.items())
print(f"\n{'All secrets set!' if ok else 'Some secrets failed — check above.'}")
