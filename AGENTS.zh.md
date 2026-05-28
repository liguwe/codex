# Rust/codex-rs

在存放 Rust 代码的 codex-rs 文件夹中：

- Crate 名称以 `codex-` 为前缀。例如，`core` 文件夹对应的 crate 名为 `codex-core`
- 使用 `format!` 时，如果可以将变量内联到 `{}` 中，始终这样做。
- 如果仓库依赖的命令（例如 `just`、`rg` 或 `cargo-insta`）尚未安装，在运行此处说明之前先安装它们。
- 永远不要添加或修改任何与 `CODEX_SANDBOX_NETWORK_DISABLED_ENV_VAR` 或 `CODEX_SANDBOX_ENV_VAR` 相关的代码。
  - 你在沙盒中运行，每当使用 `shell` 工具时，都会设置 `CODEX_SANDBOX_NETWORK_DISABLED=1`。任何使用 `CODEX_SANDBOX_NETWORK_DISABLED_ENV_VAR` 的现有代码都是在考虑到这一事实的前提下编写的。它通常用于提前退出那些作者知道你在沙盒限制下无法运行的测试。
  - 类似地，当你使用 Seatbelt（`/usr/bin/sandbox-exec`）启动进程时，子进程上会设置 `CODEX_SANDBOX=seatbelt`。想要自行运行 Seatbelt 的集成测试不能在 Seatbelt 下运行，因此对 `CODEX_SANDBOX=seatbelt` 的检查也常用于在适当时提前退出测试。
- 始终按照 https://rust-lang.github.io/rust-clippy/master/index.html#collapsible_if 折叠 if 语句
- 始终在可能的情况下内联 `format!` 参数，遵循 https://rust-lang.github.io/rust-clippy/master/index.html#uninlined_format_args
- 在可能的情况下，使用方法引用而非闭包，遵循 https://rust-lang.github.io/rust-clippy/master/index.html#redundant_closure_for_method_calls
- 避免使用 bool 或模糊的 `Option` 参数，这些参数会迫使调用方编写难以理解的代码，例如 `foo(false)` 或 `bar(None)`。优先使用 enum、命名方法、newtype 或其他符合惯用 Rust API 风格的形式，以保持调用处自文档化。
- 当无法进行该 API 更改且仍需要在 Rust 中使用小型位置字面值调用时，遵循 `argument_comment_lint` 约定：
  - 在按位置传递不透明的字面参数（如 `None`、布尔值和数字字面量）时，在其前面使用精确的 `/*param_name*/` 注释。
  - 除非注释能真正增加清晰度，否则不要为字符串或字符字面量添加这些注释；这些字面量有意免于该 lint 检查。
  - 注释中的参数名必须与被调用方签名完全匹配。
  - 可以在本地运行 `just argument-comment-lint` 来执行 lint 检查。该检查由 Bazel 驱动，因此如果 Bazel 尚未预热，第一次运行可能会较慢，但增量调用应在 15 秒内完成。大多数情况下，最好更新 PR 并让 CI 负责检查此项（或在提交 PR 后在后台异步运行）。注意 CI 会检查所有三个平台，而本地运行不会。
- 在可能的情况下，使 `match` 语句穷尽并避免使用通配符分支。
- 新添加的 trait 应包含文档注释，解释其角色以及实现应如何使用它们。
- 不鼓励在 Rust trait 中使用 `#[async_trait]` 和 `#[allow(async_fn_in_trait)]`。
  - 优先使用原生 RPITIT trait 方法，在返回的 future 上显式添加 `Send` 约束，如 `3c7f013f9735` / `#16630`。
  - 推荐的 trait 形式：
    `fn foo(&self, ...) -> impl std::future::Future<Output = T> + Send;`
  - 实现仍可使用 `async fn foo(&self, ...) -> T`，只要它们满足该契约。
  - 不要使用 `#[allow(async_fn_in_trait)]` 作为绕过显式声明 future 契约的快捷方式。
- 编写测试时，优先比较整个对象的相等性，而非逐字段比较。
- 不要在 `docs/` 文件夹中添加一般性的产品或面向用户的文档。官方的 Codex 文档存放在其他地方。例外情况是 app-server API 文档，详见下方 app-server 指南。
- 优先使用私有模块和显式导出的公共 crate API。
- 如果更改了 `ConfigToml` 或嵌套配置类型，运行 `just write-config-schema` 以更新 `codex-rs/core/config.schema.json`。
- 处理 MCP 工具调用时，优先使用 `codex-rs/codex-mcp/src/mcp_connection_manager.rs` 来处理工具和工具调用的变更。尽量最小化更改范围，利用现有抽象，而不是通过多层函数调用来传递代码。
- 如果更改了 Rust 依赖（`Cargo.toml` 或 `Cargo.lock`），从仓库根目录运行 `just bazel-lock-update` 以刷新 `MODULE.bazel.lock`，并在同一更改中包含该 lockfile 的更新。
- 依赖更改后，从仓库根目录运行 `just bazel-lock-check`，以便在 CI 之前本地捕获 lockfile 偏移。
- Bazel 不会自动将源代码树中的文件提供给编译时 Rust 文件访问。如果添加了 `include_str!`、`include_bytes!`、`sqlx::migrate!` 或类似的构建时文件或目录读取，请更新 crate 的 `BUILD.bazel`（`compile_data`、`build_script_data` 或测试数据），否则即使 Cargo 能通过，Bazel 也可能会失败。
- 不要创建只被引用一次的小型辅助方法。
- 避免过大的模块：
  - 优先添加新模块，而不是扩展现有模块。
  - Rust 模块目标应低于 500 行代码（LoC），不包括测试。
  - 如果文件超过约 800 行代码，将新功能添加到新模块中，而不是扩展现有文件，除非有充分记录的理由不这样做。
  - 此规则尤其适用于已经吸引不相关更改的高频修改文件，例如 `codex-rs/tui/src/app.rs`、`codex-rs/tui/src/bottom_pane/chat_composer.rs`、`codex-rs/tui/src/bottom_pane/footer.rs`、`codex-rs/tui/src/chatwidget.rs`、`codex-rs/tui/src/bottom_pane/mod.rs` 以及类似的中心编排模块。
  - 从大模块中提取代码时，将相关测试和模块/类型文档移至新实现附近，以便不变量与拥有它们的代码保持接近。
  - 避免向 `codex-rs/tui/src/chatwidget.rs` 添加新的独立方法，除非更改是微不足道的；优先使用新模块/文件，并保持 `chatwidget.rs` 专注于编排。
- 运行 Rust 命令（例如 `just fix` 或 `cargo test`）时，请耐心等待，永远不要尝试使用 PID 终止它们。Rust lock 可能导致执行缓慢，这是预期行为。

在完成 Rust 代码更改后，自动运行 `just fmt`（在 `codex-rs` 目录中）；无需请求批准即可运行。此外，运行测试：

1. 运行被更改项目的特定测试。例如，如果在 `codex-rs/tui` 中进行了更改，运行 `cargo test -p codex-tui`。
2. 测试通过后，如果在 common、core 或 protocol 中进行了任何更改，使用 `cargo test`（或已安装 `cargo-nextest` 时使用 `just test`）运行完整的测试套件。避免在常规本地运行中使用 `--all-features`，因为它会扩展构建矩阵并显著增加 `target/` 磁盘使用量；仅在需要完整功能覆盖时使用。项目特定的或单独的测试可以在不询问用户的情况下运行，但在运行完整测试套件之前请先询问用户。

在最终确定对 `codex-rs` 的大型更改之前，在 `codex-rs` 目录中运行 `just fix -p <project>` 以修复代码中的任何 linter 问题。优先使用 `-p` 限定范围以避免缓慢的全工作区 Clippy 构建；仅在更改了共享 crate 时才不带 `-p` 运行 `just fix`。运行 `fix` 或 `fmt` 后不要重新运行测试。

## `codex-core` crate

随着时间的推移，`codex-core` crate（定义在 `codex-rs/core/`）变得臃肿，因为它是最大的 crate，所以通常更容易将新内容添加到 `codex-core` 中，而不是重构出你需要的库代码，从而使你的新代码既不依赖也不增加 `codex-core` 的体积。

为此：**抵制向 codex-core 添加代码的冲动！**

特别是引入新概念/功能/API 时，在添加到 `codex-core` 之前，请考虑：

- 是否存在除 `codex-core` 之外的现有 crate 适合作为新代码的归属。
- 是否应该为 Cargo workspace 引入一个新的 crate 来承载新功能。根据需要重构现有代码以实现这一目标。

同样，在审查代码时，毫不犹豫地反对那些会不必要地向 `codex-core` 添加代码的 PR。

## TUI 样式约定

参见 `codex-rs/tui/styles.md`。

## TUI 代码约定

- 使用 ratatui 的 Stylize trait 提供的简洁样式辅助方法。
  - 基本跨度：使用 `"text".into()`
  - 带样式的跨度：使用 `"text".red()`、`"text".green()`、`"text".magenta()`、`"text".dim()` 等。
  - 优先使用这些方法，而不是直接使用 `Span::styled` 和 `Style` 构造样式。
  - 示例：patch 摘要文件行
    - 推荐：`vec!["  └ ".into(), "M".red(), " ".dim(), "tui/src/app.rs".dim()]`

### TUI 样式（ratatui）

- 优先使用 Stylize 辅助方法：尽可能使用 `"text".dim()`、`.bold()`、`.cyan()`、`.italic()`、`.underlined()`，而不是手动创建 Style。
- 优先使用简单转换：使用 `"text".into()` 创建 span，使用 `vec![…].into()` 创建 line；当推断存在歧义时（例如 `Paragraph::new`/`Cell::from`），使用 `Line::from(spans)` 或 `Span::from(text)`。
- 计算样式：如果 Style 在运行时计算，使用 `Span::styled` 是可以的（`Span::from(text).set_style(style)` 也可以接受）。
- 避免硬编码白色：不要使用 `.white()`；优先使用默认前景色（无颜色）。
- 链式调用：通过链式调用提高可读性（例如 `url.cyan().underlined()`）。
- 单个项目：优先使用 `"text".into()`；仅在目标类型从上下文中不明显时，或当使用 `.into()` 需要额外类型标注时，才使用 `Line::from(text)` 或 `Span::from(text)`。
- 构建行：当目标类型明显且不需要额外类型标注时，使用 `vec![…].into()` 构造 Line；否则使用 `Line::from(vec![…])`。
- 避免无谓改动：如果没有明确的 readability 或功能性提升，不要在等价形式之间重构（`Span::styled` ↔ `set_style`、`Line::from` ↔ `.into()`）；遵循文件局部约定，不要仅为了满足 `.into()` 而引入类型标注。
- 紧凑性：优先使用 rustfmt 后能保持在一行的形式；如果 `Line::from(vec![…])` 或 `vec![…].into()` 中只有一个能避免换行，选择那个。如果两者都会换行，选择换行较少的那个。

### 文本换行

- 始终使用 `textwrap::wrap` 来包裹普通字符串。
- 如果你有 ratatui Line 并想对其进行换行，使用 `tui/src/wrapping.rs` 中的辅助方法，例如 `word_wrap_lines` / `word_wrap_line`。
- 如果需要缩进换行后的行，尽可能使用 `RtOptions` 的 `initial_indent` / `subsequent_indent` 选项，而不是编写自定义逻辑。
- 如果你有一个行列表并需要在所有行前面添加某个前缀（首行和后续行的前缀可以不同），使用 `line_utils` 中的 `prefix_lines` 辅助方法。

## 测试

### 快照测试

本仓库使用快照测试（通过 `insta`），尤其是在 `codex-rs/tui` 中，用于验证渲染输出。

**要求：** 任何影响用户可见 UI 的更改（包括添加新 UI）都必须包含相应的 `insta` 快照覆盖（如果尚不存在则添加新的快照测试，或更新现有快照）。在 PR 中审查并接受快照更新，以便 UI 影响易于审查，未来的差异保持可视化。

当 UI 或文本输出有意更改时，按以下方式更新快照：

- 运行测试以生成任何更新的快照：
  - `cargo test -p codex-tui`
- 检查待处理的内容：
  - `cargo insta pending-snapshots -p codex-tui`
- 直接读取仓库中生成的 `*.snap.new` 文件来查看更改，或预览特定文件：
  - `cargo insta show -p codex-tui path/to/file.snap.new`
- 仅当你打算接受此 crate 中所有新快照时，运行：
  - `cargo insta accept -p codex-tui`

如果你没有该工具：

- `cargo install --locked cargo-insta`

### 测试断言

- 测试应使用 `pretty_assertions::assert_eq` 以获得更清晰的 diff。如果尚未导入，请在测试模块顶部导入。
- 尽可能使用深度相等比较。对整个对象执行 `assert_eq!()`，而不是对单个字段。
- 避免在测试中修改进程环境；优先从上层传递环境派生的标志或依赖。

### 在测试中启动工作区二进制文件（Cargo 与 Bazel）

- 当测试需要启动第一方二进制文件时，优先使用 `codex_utils_cargo_bin::cargo_bin("...")`，而不是 `assert_cmd::Command::cargo_bin(...)` 或 `escargot`。
  - 在 Bazel 下，二进制文件与资源可能位于 runfiles 中；使用 `codex_utils_cargo_bin::cargo_bin` 来解析在 `chdir` 后仍保持稳定的绝对路径。
- 在 Bazel 下定位 fixture 文件或测试资源时，避免使用 `env!("CARGO_MANIFEST_DIR")`。优先使用 `codex_utils_cargo_bin::find_resource!`，以便路径在 Cargo 和 Bazel runfiles 下都能正确解析。

### 集成测试（core）

- 编写端到端 Codex 测试时，优先使用 `core_test_support::responses` 中的工具。

- 所有 `mount_sse*` 辅助方法都返回一个 `ResponseMock`；保留它以便你可以对出站 `/responses` POST 主体进行断言。
- 当测试只应发出一个 POST 时使用 `ResponseMock::single_request()`，或使用 `ResponseMock::requests()` 检查每个捕获的 `ResponsesRequest`。
- `ResponsesRequest` 提供了辅助方法（`body_json`、`input`、`function_call_output`、`custom_tool_call_output`、`call_output`、`header`、`path`、`query_param`），以便断言可以针对结构化 payload，而不是手动解析 JSON。
- 使用提供的 `ev_*` 构造函数和 `sse(...)` 构建 SSE payload。
- 优先使用 `wait_for_event` 而不是 `wait_for_event_with_timeout`。
- 优先使用 `mount_sse_once` 而不是 `mount_sse_once_match` 或 `mount_sse_sequence`。

- 典型模式：

  ```rust
  let mock = responses::mount_sse_once(&server, responses::sse(vec![
      responses::ev_response_created("resp-1"),
      responses::ev_function_call(call_id, "shell", &serde_json::to_string(&args)?),
      responses::ev_completed("resp-1"),
  ])).await;

  codex.submit(Op::UserTurn { ... }).await?;

  // 如果需要，断言请求主体。
  let request = mock.single_request();
  // 使用 request.function_call_output(call_id) 或 request.json_body() 或其他辅助方法进行断言。
  ```

## App-server API 开发最佳实践

这些指南适用于 `codex-rs` 中的 app-server 协议工作，尤其是：

- `app-server-protocol/src/protocol/common.rs`
- `app-server-protocol/src/protocol/v2.rs`
- `app-server/README.md`

### 核心规则

- 所有活跃的 API 开发都应在 app-server v2 中进行。不要向 v1 添加新的 API 表面积。
- 遵循 payload 命名一致性：
  请求 payload 使用 `*Params`，响应使用 `*Response`，通知使用 `*Notification`。
- 将 RPC 方法暴露为 `<resource>/<method>`，并保持 `<resource>` 为单数（例如 `thread/read`、`app/list`）。
- 始终在 wire 上以 camelCase 暴露字段，使用 `#[serde(rename_all = "camelCase")]`，除非标记联合或显式兼容性需求需要针对性重命名。
- 例外：config RPC payload 预期使用 snake_case 以镜像 config.toml 键（参见 `app-server-protocol/src/protocol/v2.rs` 中的 config 读/写/列表 API）。
- 始终在 v2 请求/响应/通知类型上设置 `#[ts(export_to = "v2/")]`，以便生成的 TypeScript 落入正确的命名空间。
- 永远不要对 v2 API payload 字段使用 `#[serde(skip_serializing_if = "Option::is_none")]`。
  例外：客户端到服务器的请求如果确实没有参数，可以使用：
  `params: #[ts(type = "undefined")] #[serde(skip_serializing_if = "Option::is_none")] Option<()>`。
- 保持 Rust 和 TS wire 重命名一致。如果字段或变体使用了 `#[serde(rename = "...")]`，添加匹配的 `#[ts(rename = "...")]`。
- 对于可区分联合，在两个序列化器中使用显式标记：
  `#[serde(tag = "type", ...)]` 和 `#[ts(tag = "type", ...)]`。
- 在 API 边界优先使用普通 `String` ID（如果需要，在内部进行 UUID 解析/转换）。
- 时间戳应为整数 Unix 秒（`i64`），命名为 `*_at`（例如 `created_at`、`updated_at`、`resets_at`）。
- 对于实验性 API 表面积：
  使用 `#[experimental("method/or/field")]`，当需要字段级门控时派生 `ExperimentalApi`，当方法中只有部分字段为实验性时，在 `common.rs` 中使用 `inspect_params: true`。

### 客户端到服务器请求 payload（`*Params`）

- 每个可选字段都必须使用 `#[ts(optional = nullable)]` 注解。不要在客户端到服务器请求 payload（`*Params`）之外使用 `#[ts(optional = nullable)]`。
- 可选集合字段（例如 `Vec`、`HashMap`）必须使用 `Option<...>` + `#[ts(optional = nullable)]`。不要使用 `#[serde(default)]` 来建模可选集合，也不要在 v2 payload 字段上使用 `skip_serializing_if`。
- 当你希望省略表示布尔字段为 `false` 时，对 `Option<bool>` 优先使用 `#[serde(default, skip_serializing_if = "std::ops::Not::not")] pub field: bool`。
- 对于新的列表方法，默认实现游标分页：
  请求字段 `pub cursor: Option<String>` 和 `pub limit: Option<u32>`，
  响应字段 `pub data: Vec<...>` 和 `pub next_cursor: Option<String>`。

### 开发工作流

- 当 API 行为更改时更新 app-server 文档/示例（至少更新 `app-server/README.md`）。
- 当 API 形状更改时重新生成 schema fixture：
  `just write-app-server-schema`
  （当实验性 API fixture 受影响时，还需要 `just write-app-server-schema --experimental`）。
- 使用 `cargo test -p codex-app-server-protocol` 进行验证。
- 避免仅针对 `common.rs` 中单个请求字段的实验性字段标记编写样板测试；依赖 schema 生成/测试和行为覆盖。
