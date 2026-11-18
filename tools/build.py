"""Convert Sparkle's Surge distribution to Stash overrides."""
import argparse
import hashlib
import json
import re
import shlex
import subprocess
from pathlib import Path
from urllib.request import urlopen

import yaml

UPSTREAM = "https://raw.githubusercontent.com/kokoryh/Sparkle/refs/heads/master/"
PROJECT = Path(__file__).resolve().parents[1]
CORE = ("bilibili", "bilibili-manga", "youtube", "block-ad", "weibo-intl", "12306")
PARAMS = {
    "动态最常访问": ("display_up_list", ["auto", "show", "hide"]),
    "创作中心": ("creator_hub", False),
    "过滤置顶评论广告": ("purify_comment", True),
    "优化评论区加载": ("optimize_comments", True),
    "空降助手": ("sponsor_block", True),
    "空降助手策略": ("sponsor_policy", "DIRECT"),
    "屏蔽P2P": ("block_p2p", ["OR", "AND"]),
    "日志等级": ("log_level", ["1", "2", "3", "4", "5"]),
    "屏蔽上传按钮": ("block_upload", True),
    "屏蔽选段按钮": ("block_immersive", True),
    "屏蔽Shorts按钮": ("block_shorts", True),
    "字幕翻译语言": ("caption_lang", "off"),
    "启用调试模式": ("debug", False),
    "STUN": ("stun", ["OR", "AND"]),
    "通用域名": ("ad_domains", ["OR", "AND"]),
    "系统更新": ("system_update", ["AND", "OR"]),
    "refname": ("refname", "refs/heads/dev"),
    "SubStore同步": ("substore_cron", "0 5 * * *"),
    "毛怪俱乐部签到": ("mgclub_cron", "55 2 * * *"),
    "port": ("port", 5753),
    "secret": ("secret", ""),
    "ipv6": ("ipv6", False),
    "dc-config-url": ("dc_config_url", "https://ruleset.skk.moe/Internal/mtproto-dc-config.json"),
}


def arg(name, *, json_value=False):
    suffix = "|json" if json_value else ""
    return "${args." + PARAMS[name][0] + suffix + "}"


def parameter(name, default):
    key, choices = PARAMS[name]
    result = {"title": name}
    if choices in (["OR", "AND"], ["AND", "OR"]):
        enabled = default != "#"
        result.update(type="select", default="OR" if enabled else "AND", options=[
            {"value": "OR", "label": "开启"},
            {"value": "AND", "label": "关闭"},
        ])
    elif isinstance(choices, list):
        result.update(type="select", default=choices[0] if default not in choices else default,
                      options=[{"value": opt} for opt in choices])
    elif isinstance(choices, bool):
        result.update(type="switch", default=default.lower() not in {"0", "false", "#"})
    elif isinstance(choices, int):
        result.update(type="input", default=int(default), **{"value-type": "integer", "minimum": 1, "maximum": 65535})
    elif name == "secret":
        result.update(type="input", required=True, **{"min-length": 32, "max-length": 34})
    else:
        result.update(type="input", default=default, required=True)
    return key, result


def read_module(path):
    meta, sections = {}, {}
    section = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line.startswith("#!"):
            key, value = line[2:].split("=", 1)
            meta[key] = value
        elif line.startswith("[") and line.endswith("]"):
            section = sections.setdefault(line[1:-1], [])
        elif line and not line.startswith(("#", "//")):
            if section is None:
                raise ValueError(f"{path}: {line}")
            section.append(line)
    return meta, {key: lines for key, lines in sections.items() if lines}


def script_options(line):
    _, data = line.split(" = ", 1)
    parts = re.split(r",(?=(?:type|pattern|argument|requires-body|binary-body-mode|max-size|engine|timeout|script-path|cronexp|wake-system)=)", data)
    return dict(part.rstrip(",").split("=", 1) for part in parts)


class Scripts:
    def __init__(self, upstream, candidates):
        self.upstream = upstream
        self.candidates = candidates
        self.local = {}
        self.external = {}
        self.refs = {}

    def add(self, url):
        if url.startswith(UPSTREAM + "dist/"):
            stem = url.rsplit("/", 1)[1]
            source = (self.upstream / "dist" / stem).read_text()
            if source.count("abort(){$done({abort:!0})}") != 1:
                raise ValueError(f"Review Stash abort adapter for {stem}")
            source = source.replace("abort(){$done({abort:!0})}", "abort(){$done()}")
            if stem.startswith("bilibili.protobuf."):
                if "$utils.ungzip(" not in source:
                    raise ValueError(f"Review Stash gzip adapter for {stem}")
                fflate = (PROJECT / "node_modules/fflate/umd/index.js").read_text()
                source = (
                    "(() => {\nconst $utils = (() => {\nconst module = {exports: {}}; const exports = module.exports;\n"
                    + fflate + "\nreturn {ungzip: module.exports.gunzipSync};\n})();\n"
                    + source + "\n})();\n"
                )
            if stem == "bilibili.protobuf.request.js":
                # Stash does not expose a writable trailers field. Preserve gRPC status in
                # the synthetic initial headers when a callback exposes trailers.
                adapter = '''
const stashClient = $httpClient;
$httpClient = Object.create(stashClient);
$httpClient.post = (request, callback) => stashClient.post(request, (error, response, body) => {
    if (response && response.trailers) {
        response = {...response, headers: {...response.headers, ...response.trailers}};
        delete response.trailers;
    }
    callback(error, response, body);
});
'''
                # Use a local parameter for the adapter. The host's global can be read-only.
                source = "(($httpClient) => {" + adapter + source + "\n})($httpClient);\n"
            self.local[stem] = source
            return "sparkle." + stem, f"@LOCAL@/{stem}"
        if url not in self.external:
            match = re.fullmatch(r"https://raw\.githubusercontent\.com/([^/]+/[^/]+)/([^/]+)/(.+\.js)", url)
            if not match:
                raise ValueError(f"Unsupported script URL: {url}")
            repo, ref, path = match.groups()
            if (repo, ref) not in self.refs:
                result = subprocess.check_output(["git", "ls-remote", "--exit-code",
                                                  f"https://github.com/{repo}.git", f"refs/heads/{ref}"], text=True)
                self.refs[repo, ref] = result.split()[0]
            pinned = f"https://raw.githubusercontent.com/{repo}/{self.refs[repo, ref]}/{path}"
            stem = Path(path).name
            with urlopen(pinned, timeout=30) as response:
                (self.candidates / stem).write_bytes(response.read())
            self.external[url] = ("sparkle." + stem, pinned)
        return self.external[url]


def convert(path, scripts):
    module = path.stem
    meta, sections = read_module(path)
    config = {"name": meta["name"], "desc": meta["desc"]}
    http, providers, params = {}, {}, {}
    defaults = dict(item.split(":", 1) for item in meta.get("arguments", "").split(",") if item)
    for key, default in defaults.items():
        if key in PARAMS and key not in {"interface"}:
            params.update([parameter(key, default)])
    if params:
        config.update({"arguments-version": 1, "arguments": params})

    for section, lines in sections.items():
        if section == "MITM":
            assert len(lines) == 1 and lines[0].startswith("hostname = %APPEND% ")
            http["mitm"] = lines[0].split("%APPEND% ", 1)[1].split(", ")
        elif section == "URL Rewrite":
            http["url-rewrite"] = [re.sub(r"\{\{\{([^}]+)}}}", lambda m: arg(m[1]), line) for line in lines]
        elif section == "Body Rewrite":
            rewrites = []
            for line in lines:
                kind, pattern, expression = line.split(" ", 2)
                assert kind == "http-response-jq" and expression[0] == expression[-1] == "'"
                rewrites.append(f"{pattern} response-jq {expression[1:-1]}")
            http["body-rewrite"] = rewrites
        elif section == "Map Local":
            mocks = []
            for line in lines:
                pattern, _, rest = line.partition(" header=")
                match = re.fullmatch(r'"(.*?)" data-type=(base64|text) data="(.*)"', rest)
                if not match:
                    raise ValueError(f"Unsupported Map Local: {line}")
                headers, kind, body = match.groups()
                mocks.append({"match": pattern, "headers": dict(h.split(": ", 1) for h in headers.split("|")),
                              kind: body.replace(r'\"', '"')})
            http["mock"] = mocks
        elif section == "Rule":
            rules = []
            for line in lines:
                line = line.replace(",extended-matching", "").replace(",REJECT-NO-DROP", ",REJECT")
                match = re.match(r"^\{\{\{([^}]+)}}},([^,]+),(.+)$", line)
                if match:
                    toggle, value, policy = match.groups()
                    kind = {"屏蔽P2P": "DST-PORT", "STUN": "PROTOCOL",
                            "通用域名": "DOMAIN", "系统更新": "DOMAIN"}[toggle]
                    condition = f"{arg(toggle)},((DST-PORT,1),(NOT,((DST-PORT,1))))"
                    line = f"AND,(({kind},{value}),({condition})),{policy}"
                line = re.sub(r"\{\{\{([^}]+)}}}", lambda m: arg(m[1]), line)
                rules.append(line)
            config["rules"] = rules
        elif section == "Script":
            for line in lines:
                options = script_options(line)
                name, url = scripts.add(options.pop("script-path"))
                kind = options.pop("type")
                providers[name] = {"url": url, "interval": 86400}
                entry = {"name": name}
                if "timeout" in options:
                    entry["timeout"] = int(options.pop("timeout"))
                if kind == "cron":
                    entry["cron"] = re.sub(r"\{\{\{([^}]+)}}}", lambda m: arg(m[1]), options.pop("cronexp"))
                    assert options.pop("wake-system") == "1"
                    config.setdefault("cron", {}).setdefault("script", []).append(entry)
                else:
                    entry.update(type=kind.removeprefix("http-"), match=options.pop("pattern"))
                    assert kind in {"http-request", "http-response"}
                    entry["require-body"] = options.pop("requires-body", "0") in {"1", "true"}
                    if options.pop("binary-body-mode", None):
                        entry["binary-mode"] = True
                    if options.pop("engine", None) == "webview":
                        entry["engine"] = "webkit"
                    assert options.pop("max-size", "-1") == "-1"
                    argument = options.pop("argument", None)
                    if argument:
                        entry["argument"] = re.sub(
                            r'"\{\{\{([^}]+)}}}"|\{\{\{([^}]+)}}}',
                            lambda m: arg(m[1] or m[2], json_value=True), argument[1:-1])
                    if line.startswith(("{{{优化评论区加载}}}", "{{{空降助手}}}")):
                        toggle = "优化评论区加载" if line.startswith("{{{优化评论区加载}}}") else "空降助手"
                        entry["argument"] = entry["argument"][:-1] + ',"enabled":' + arg(toggle, json_value=True) + "}"
                    http.setdefault("script", []).append(entry)
                if options:
                    raise ValueError(f"Unsupported script options: {options}")
        elif section == "General" and module == "boxjs":
            assert lines == ["force-http-engine-hosts = %APPEND% boxjs.com"]
            http["force-http-engine"] = ["boxjs.com"]
        elif section == "General" and module == "general":
            general = dict(line.split(" = ", 1) for line in lines)
            assert set(general) == {"{{{always-real-ip}}}", "{{{skip-proxy}}}", "{{{hide-vpn-icon}}}"}
            config["dns"] = {"fake-ip-filter": general["{{{always-real-ip}}}"].split("%APPEND% ", 1)[1].split(", ")}
        elif section == "MTProto":
            assert set(line.split(" = ")[0] for line in lines) == {"interface", "port", "secret", "ipv6", "dc-config-url"}
            config["mtproto"] = {key: arg(key) for key in ("port", "secret", "ipv6", "dc-config-url")}
        else:
            raise ValueError(f"Unsupported section {section} in {module}")
    if http:
        config["http"] = http
    if providers:
        config["script-providers"] = providers
    return config


def merge(configs):
    combined = {"name": "Sparkle-Stash", "desc": "哔哩哔哩、YouTube、微博轻享版与常用应用去广告"}
    for config in configs:
        for key in ("arguments", "http", "script-providers", "rules"):
            if key in config:
                merge_value(combined, key, config[key])
    combined["arguments-version"] = 1
    return combined


def merge_value(target, key, value):
    if isinstance(value, dict):
        for child, item in value.items():
            merge_value(target.setdefault(key, {}), child, item)
    elif isinstance(value, list):
        target.setdefault(key, []).extend(value)
    else:
        if key in target and target[key] != value:
            raise ValueError(f"Incompatible override field {key}")
        target[key] = value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("repository")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    args.candidates.mkdir(parents=True, exist_ok=True)
    scripts = Scripts(args.upstream, args.candidates)
    source = args.upstream / "release/surge"
    modules = {}
    for path in sorted((source / "module").glob("*.sgmodule")):
        if path.stem == "extra":
            _, sections = read_module(path)
            assert set(sections) == {"General"} and len(sections["General"]) == 6
            continue  # External access and LAN exposure are set in the Stash app.
        modules[path.stem] = convert(path, scripts)
    modules["Sparkle-Stash"] = merge([modules[name] for name in CORE])
    upstream = subprocess.check_output(["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True).strip()
    contents = {f"{name}.stoverride": yaml.safe_dump(config, allow_unicode=True, sort_keys=False, width=10000)
                for name, config in modules.items()}
    for stem, script in scripts.local.items():
        # Wrap the optional request interception only. Response processing remains independent.
        if stem == "bilibili.protobuf.request.js":
            script = "if (typeof $argument === 'string' && JSON.parse($argument).enabled === false) { $done({}); } else {\n" + script + "\n}\n"
        contents[f"scripts/{stem}"] = script
    rule_dir = source / "rule"
    assert {path.name for path in rule_dir.iterdir()} == {"Twitter.list"}
    rules = (rule_dir / "Twitter.list").read_text().splitlines()
    contents["rules/Twitter.yaml"] = yaml.safe_dump({"payload": rules})
    contents["LICENSE.fflate"] = (PROJECT / "node_modules/fflate/LICENSE").read_text()
    contents["LICENSE"] = (args.upstream / "LICENSE").read_text()
    contents["upstream.json"] = json.dumps({"upstream": upstream, "external_scripts": scripts.external},
                                          ensure_ascii=False, indent=2) + "\n"
    version = hashlib.sha256(json.dumps(contents, sort_keys=True).encode()).hexdigest()
    base = f"https://raw.githubusercontent.com/{args.repository}/published/versions/{version}/scripts"
    for name, content in contents.items():
        path = args.out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.replace("@LOCAL@", base))
    (args.out / "version").write_text(version + "\n")


if __name__ == "__main__":
    main()
