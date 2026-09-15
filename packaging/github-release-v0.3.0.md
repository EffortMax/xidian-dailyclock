Windows x64 单文件版本，无需预装 Python。

## v0.3.0 重点

- 可选保存账户和密码；密码使用当前 Windows 用户的 DPAPI 加密，默认不保存。
- 桌面端按精确 BJDM 退课，提交前必须连续确认两次。
- 退课接口返回成功后继续复核已选课程，只有 BJDM 确实消失才报告成功。
- 保留桌面/CLI 无人值守、ddddocr、人工验证码、多目标自动选课与 CSV 课表导出。

## 下载

- `XDU-Course-Assistant-v0.3.0-windows-x64.exe`
- `XDU-Course-Assistant-v0.3.0-windows-x64.exe.sha256`

请使用同名 `.sha256` 文件校验下载结果。该 EXE 未做商业代码签名；SmartScreen 提示未知发布者时，请先核对仓库地址和校验值。

## 验证

- Python `compileall` 通过。
- 单元与 PySide6 离屏 UI 测试 24/24 通过。
- 发布 EXE 的 ddddocr 模型、ONNX Runtime 与 Windows DPAPI 自检通过。
- 本地同配置构建已完成 GUI 启动冒烟，窗口版本为 0.3.0。

用户此前已确认真实登录、课程选择和课表导出通过。本次发布没有为了测试而退掉真实课程；退课路径以精确 BJDM mock、服务器拒绝分支、最终移除复核和双确认 UI 测试覆盖。

完整安全说明、复现命令与审计记录见 [`docs/release-v0.3.0.md`](https://github.com/EffortMax/xidian-dailyclock/blob/v0.3.0/docs/release-v0.3.0.md)。
