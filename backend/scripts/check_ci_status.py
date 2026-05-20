import os
import urllib.request, json

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

req = urllib.request.Request(
    "https://api.github.com/repos/shreyaaassss/cadencia-magic-wallet/actions/runs?per_page=3",
    headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
)
with urllib.request.urlopen(req) as r:
    data = json.loads(r.read())

for run in data["workflow_runs"]:
    name = run["name"]
    status = run["status"]
    conclusion = run["conclusion"] or "in-progress"
    created = run["created_at"]
    url = run["html_url"]
    print(f"{name} | {status} | {conclusion} | {created}")
    print(f"  {url}")
