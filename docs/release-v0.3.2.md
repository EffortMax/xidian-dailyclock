# v0.3.2 Windows 发布记录

## 产物

- 文件：`release/XDU-Course-Assistant-v0.3.2-windows-x64.exe`
- 本地参考构建大小：`65,527,233` 字节（`62.49 MiB`）
- 本地参考构建 SHA-256：`c9557b7a4fe352651ff1464e2f826336146ec025a03b9ef31b7e0ae8ecc9b4a2`
- Python：`3.13.0`
- PyInstaller：`6.16.0`
- 平台：Windows 11 x64

GitHub Actions 使用固定依赖在 `windows-latest` 重新构建，正式发布附件可能因 Python 补丁版本或构建环境不同而具有不同哈希；应以 Release 同名 `.sha256` 附件为准。

## 更新范围

- 自动选课每轮输出编号心跳、待处理目标数量和下次等待时间。
- 自动选课服务日志通过 Qt 工作线程信号安全返回主线程。
- 统一页面间距、控件宽度和按钮功能分组。
- 运行日志改为可拖动、可展开的面板，并增加时间戳、条数、自动滚动、复制、保存和确认清空。
- 日志面板尺寸及自动滚动设置通过 `QSettings` 持久化。

## 本地发布验证

- `compileall`：通过。
- 自动化测试：31 项全部通过。
- 源码依赖自检：退出码 0。
- PyInstaller 归档审计：80 个顶层成员、470 个 PYZ 成员，无禁用组件。
- 打包后 OCR 与 Windows DPAPI 自检：退出码 0。
- PE `FileVersion` 与 `ProductVersion`：均为 `0.3.2`。
- 子进程感知 GUI 启动检查：检测到 2 个单文件父/子进程，窗口启动后保持运行。
- SHA-256 校验文件复核：通过。

发布说明正文见 [`../packaging/github-release-v0.3.2.md`](../packaging/github-release-v0.3.2.md)。
