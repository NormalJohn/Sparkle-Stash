"""Check generated Stash data, upstream coverage and native rewrite fixtures."""
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from build import CORE, read_module

upstream, stage = map(Path, sys.argv[1:])
source = upstream / "release/surge/module"
version = (stage / "version").read_text().strip()
assert re.fullmatch("[0-9a-f]{64}", version)
configs = {p.stem: yaml.safe_load(p.read_text()) for p in stage.glob("*.stoverride")}
assert set(configs) == ({p.stem for p in source.glob("*.sgmodule")} - {"extra"}) | {"Sparkle-Stash"}
for module, config in configs.items():
    http = config.get("http", {})
    providers = config.get("script-providers", {})
    specs = config.get("arguments", {})
    assert all(spec["description"].strip() for spec in specs.values()), module
    if module != "Sparkle-Stash":
        _, original = read_module(source / f"{module}.sgmodule")
        for section, key in (("Map Local", "mock"), ("Body Rewrite", "body-rewrite"), ("URL Rewrite", "url-rewrite")):
            assert len(original.get(section, [])) == len(http.get(key, [])), (module, section)
        assert len(original.get("Script", [])) == len(http.get("script", [])) + len(config.get("cron", {}).get("script", []))
        assert len(original.get("Rule", [])) == len(config.get("rules", []))
    else:
        for key in ("script", "mock", "body-rewrite", "url-rewrite"):
            assert len(http.get(key, [])) == sum(len(configs[name].get("http", {}).get(key, [])) for name in CORE)
    text = json.dumps(config, ensure_ascii=False)
    assert "@LOCAL@" not in text and "{{{" not in text
    assert set(re.findall(r"\$\{args\.([A-Za-z_0-9]+)(?:\|json)?}", text)) == set(specs)
    for entry in http.get("script", []) + config.get("cron", {}).get("script", []):
        assert entry["name"] in providers
        if "match" in entry:
            re.compile(entry["match"])
            assert entry["type"] in {"request", "response"}
            if "protobuf" in entry["name"] or "youtube" in entry["name"]:
                assert entry["binary-mode"] and entry["require-body"]
        if "argument" in entry:
            def replace(match):
                spec = specs[match[1]]
                return json.dumps(spec["default"], ensure_ascii=False)
            json.loads(re.sub(r"\$\{args\.([A-Za-z_0-9]+)\|json}", replace, entry["argument"]))
    for provider in providers.values():
        url = provider["url"]
        assert re.fullmatch(r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/(?:[a-f0-9]{40}/.+|published/versions/" + version + r"/scripts/[^/]+)", url)
        if f"/versions/{version}/scripts/" in url:
            assert (stage / "scripts" / url.rsplit("/", 1)[1]).is_file()
    for mock in http.get("mock", []):
        re.compile(mock["match"])
        if "base64" in mock:
            body = base64.b64decode(mock["base64"], validate=True)
            assert body[0] == 0 and int.from_bytes(body[1:5], "big") == len(body) - 5
        else:
            json.loads(mock["text"])
    for rule in http.get("body-rewrite", []):
        pattern, kind, expression = rule.split(" ", 2)
        re.compile(pattern)
        assert kind == "response-jq"
        subprocess.run(["jq", "-n", "if false then (" + expression + ") else null end"], check=True, capture_output=True)

for module in ("bilibili", "Sparkle-Stash"):
    sponsor_policy = configs[module]["arguments"]["sponsor_policy"]
    assert sponsor_policy["default"] == "DIRECT"
    assert all(term in sponsor_policy["description"] for term in ("DIRECT", "策略组", "bsbsb.top"))

kfc = configs["block-ad"]["http"]["body-rewrite"][0].split(" ", 2)[2]
result = subprocess.check_output(["jq", "-c", kfc], input=b'{"data":{"app6_bootStrapAd":1,"keep":2}}')
assert json.loads(result) == {"data": {"keep": 2}}
assert yaml.safe_load((stage / "rules/Twitter.yaml").read_text())["payload"] == (
    upstream / "release/surge/rule/Twitter.list").read_text().splitlines()
print(f"Validated {len(configs)} overrides, native mocks, rewrite expressions and immutable provider URLs.")
