# Sparkle-Stash

适用于 iOS Stash 3.7 及以上版本的 [Sparkle](https://github.com/kokoryh/Sparkle) 移植。安装时可在 Stash 中设置覆写参数，远程更新后会保留适用的个人设置。

## 安装

将以下地址添加到 Stash 的「覆写」并启用。HTTPS 改写需要先安装并信任 Stash 的 CA，再开启 MitM。

```text
https://raw.githubusercontent.com/NormalJohn/Sparkle-Stash/published/Sparkle-Stash.stoverride
```

主覆写包含哔哩哔哩（含 SponsorBlock、装扮、自定义参数和 Protobuf）、哔哩哔哩漫画、YouTube 增强、微博轻享版、12306 和通用应用广告过滤。微博轻享版继承上游的版本限制（6.6.8）。只需要部分功能时，可从 [published 分支](https://github.com/NormalJohn/Sparkle-Stash/tree/published) 选择对应覆写。主覆写与其中已包含的单项覆写择一启用。

`boxjs`、`substore`、`scheduled-tasks`、`mtproto`、`general`、`block`、`redirect`、`safari-search`、`dev` 和其他网页增强覆写可按需单独安装。Safari 搜索扩展要求 Safari 的搜索引擎设为 DuckDuckGo。Twitter 规则集位于 `published` 分支的当前版本目录 `versions/<version>/rules/Twitter.yaml`，在 Stash 中以 `classical` 类型载入并指定出站策略。

## 与 Surge 的差异

- `general` 将 `always-real-ip` 转成 Stash 的 `dns.fake-ip-filter`。Surge 的 `skip-proxy` 和 `hide-vpn-icon` 没有在覆写中直接映射。
- 上游 `extra` 对应 Stash 的「允许局域网连接」和「设置 → 外部访问」。需要这些功能时，在 App 内设置端口和个人 API 密钥。
- MTProto 使用 Stash 自带监听方式和局域网开关，安装后需填写自己的 MTProto 密钥。定时任务需要 Stash VPN 在线，停用时可关闭覆写，或把单项任务的 Cron 设为永不出现的日期（`0 0 31 2 *`）。
- Surge 的 `extended-matching` 已省略，`REJECT-NO-DROP` 使用 Stash 的 `REJECT`。脚本合成 gRPC 响应时，将可见的 trailers 转为响应头。此适配器不能处理 Stash 未向脚本公开的 trailers。

## 更新与验证

GitHub Actions 每 6 小时检查上游默认分支。它先生成候选覆写并运行配置、原生 jq 表达式、二进制 mock 和脚本接口回归，再将整套文件一次性推送到 `published` 分支。测试失败时保留上次发布。每个版本使用独立的本地脚本路径，第三方脚本 URL 固定到经过检查的 Git 提交。记录原始上游提交和引用的第三方脚本见 [upstream.json](https://github.com/NormalJohn/Sparkle-Stash/blob/published/upstream.json)。

自动测试使用模拟 Stash 脚本接口，包含 SponsorBlock 的固定响应、gzip 与未压缩 Protobuf、广告过滤及个性化配置。iOS 实机导入、真实客户端流量和第三方服务账户功能需在实际环境验证。第三方大型脚本在 CI 中进行语法检查。

本地运行需要 Python 3、Node 24、Git 和 jq。

```sh
npm ci --ignore-scripts
python -m pip install -r requirements.txt
git clone --depth 1 https://github.com/kokoryh/Sparkle.git /tmp/sparkle-upstream
python tools/build.py /tmp/sparkle-upstream /tmp/sparkle-output /tmp/sparkle-external NormalJohn/Sparkle-Stash
python tests/config.py /tmp/sparkle-upstream /tmp/sparkle-output
node tests/runtime.mjs /tmp/sparkle-output /tmp/sparkle-external
```

Sparkle 的对应源码可由 `upstream.json` 中的提交定位。移植和适配器遵循仓库中的 GPLv3 许可，fflate 的 MIT 许可随发布附送。
