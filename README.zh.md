<p align="center"><code>npm i -g @openai/codex</code><br />或 <code>brew install --cask codex</code></p>
<p align="center"><strong>Codex CLI</strong> 是来自 OpenAI 的一款编码智能体，可在您的本地电脑上运行。
<p align="center">
  <img src="https://github.com/openai/codex/blob/main/.github/codex-cli-splash.png" alt="Codex CLI splash" width="80%" />
</p>
</br>
如果您希望在代码编辑器（VS Code、Cursor、Windsurf）中使用 Codex，请<a href="https://developers.openai.com/codex/ide">在 IDE 中安装。</a>
</br>如果您希望体验桌面应用，请运行 <code>codex app</code> 或访问 <a href="https://chatgpt.com/codex?app-landing-page=true">Codex 应用页面</a>。
</br>如果您在寻找 OpenAI 的<em>云端智能体</em> <strong>Codex Web</strong>，请前往 <a href="https://chatgpt.com/codex">chatgpt.com/codex</a>。</p>

---

## 快速开始

### 安装并运行 Codex CLI

使用您喜欢的包管理器进行全局安装：

```shell
# 使用 npm 安装
npm install -g @openai/codex
```

```shell
# 使用 Homebrew 安装
brew install --cask codex
```

然后只需运行 `codex` 即可开始使用。

<details>
<summary>您也可以前往 <a href="https://github.com/openai/codex/releases/latest">GitHub 最新版本</a>，下载适合您平台的二进制文件。</summary>

每个 GitHub Release 包含多个可执行文件，但实际上您需要的可能是以下之一：

- macOS
  - Apple Silicon/arm64：`codex-aarch64-apple-darwin.tar.gz`
  - x86_64（较旧的 Mac 硬件）：`codex-x86_64-apple-darwin.tar.gz`
- Linux
  - x86_64：`codex-x86_64-unknown-linux-musl.tar.gz`
  - arm64：`codex-aarch64-unknown-linux-musl.tar.gz`

每个压缩包内都包含一个带有平台名称的文件（例如 `codex-x86_64-unknown-linux-musl`），解压后您可能需要将其重命名为 `codex`。

</details>

### 通过 ChatGPT 订阅计划使用 Codex

运行 `codex` 并选择 **Sign in with ChatGPT**。我们建议您登录 ChatGPT 账号，通过 Plus、Pro、Business、Edu 或 Enterprise 计划来使用 Codex。[了解更多关于 ChatGPT 计划包含的内容](https://help.openai.com/en/articles/11369540-codex-in-chatgpt)。

您也可以使用 API 密钥来运行 Codex，但这需要[额外的设置](https://developers.openai.com/codex/auth#sign-in-with-an-api-key)。

## 文档

- [**Codex 文档**](https://developers.openai.com/codex)
- [**贡献指南**](./docs/contributing.md)
- [**安装与构建**](./docs/install.md)
- [**开源基金**](./docs/open-source-fund.md)

本仓库采用 [Apache-2.0 许可证](LICENSE) 授权。

---

## 备注

> 本目录作为上游仓库的本地镜像使用。本地的翻译文件和备注（如 `*.zh.md`）均不提交至远端，以避免与上游更新产生冲突。构建和测试不受这些本地文件影响。
