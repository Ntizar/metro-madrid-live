#!/usr/bin/env python3
"""Crea el repo en GitHub, sube main y activa Pages. No imprime el token."""
import os, re, json, subprocess, urllib.request

env = open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8").read()
tok = re.search(r"^GITHUB_TOKEN\s*=\s*['\"]?([^'\"\s]+)", env, re.M).group(1)
H = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
     "Content-Type": "application/json", "User-Agent": "mastermind"}


def api(method, path, data=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 headers=H, data=json.dumps(data).encode() if data else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


REPO = "metro-madrid-live"
st, user = api("GET", "/user")
owner = user["login"]
print("owner:", owner)

st, body = api("POST", "/user/repos", {
    "name": REPO, "description": "Metro de Madrid bajo tierra: visor 3D con GTFS del CRTM y diseño Aurora",
    "homepage": f"https://{owner.lower()}.github.io/{REPO}/", "private": False, "has_issues": True})
print("crear repo:", st, body.get("message", "ok"))

remote = f"https://x-access-token:{tok}@github.com/{owner}/{REPO}.git"
d = os.path.expanduser("~/Projects/metro-madrid-live")
subprocess.run(["git", "-C", d, "remote", "remove", "origin"], capture_output=True)
subprocess.run(["git", "-C", d, "remote", "add", "origin", remote], check=True)
subprocess.run(["git", "-C", d, "branch", "-M", "main"], check=True)
r = subprocess.run(["git", "-C", d, "push", "-u", "origin", "main"], capture_output=True, text=True)
print("push:", r.returncode, (r.stderr or r.stdout).replace(tok, "***")[-300:])

st, body = api("POST", f"/repos/{owner}/{REPO}/pages",
               {"source": {"branch": "main", "path": "/"}})
print("pages:", st, body.get("message", body.get("html_url", "ok")))
