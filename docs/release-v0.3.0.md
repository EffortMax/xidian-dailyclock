# XDU Course Assistant v0.3.0

发布日期：2026-09-15

## 主要变化

- 登录页新增可选的账户和密码保存；密码使用当前 Windows 用户的 DPAPI 加密，默认不保存。
- 桌面课程页新增退课入口，严格按选中行的 BJDM 操作。
- 任何退课请求提交前都必须连续通过两次确认；第二次确认明确提示课程可能无法重新选回。
- 退课成功不能只依赖接口返回值，还必须复核该 BJDM 已从已选课程中消失。
- 保留无人值守 CLI、桌面 OCR / 人工验证码、多目标自动选课和 CSV 课表导出。
- 新增可复现的 Windows x64 单文件 EXE 构建与发布包自检。

## 下载与校验

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `XDU-Course-Assistant-v0.3.0-windows-x64.exe` | 198,955,776 字节 | `d23a3887dcec1305ad0845d7480e9b079d38d7545151a2014a9441f3e91ecde0` |
| `XDU-Course-Assistant-v0.3.0-windows-x64.exe.sha256` | 校验文件 | 与上值一致 |

```powershell
Get-FileHash .\XDU-Course-Assistant-v0.3.0-windows-x64.exe -Algorithm SHA256
```

## 安全说明

- 凭据保存是 opt-in；未勾选时不会创建凭据文件。
- `%LOCALAPPDATA%\DailyClockXDU\credentials.json` 中账户标识可读，但密码仅保存为 DPAPI 密文。
- DPAPI 密文绑定当前 Windows 用户；它不能防止已经控制该 Windows 会话的恶意程序。
- Cookie 仍等同登录凭据，不能提交到 Git、上传或发送给他人。
- EXE 未做商业代码签名；若 SmartScreen 提示未知发布者，请核对 GitHub 发布来源与 SHA-256。

## 验证记录

| 项目 | 结果 |
|---|---|
| Python `compileall` | 通过 |
| 单元与 PySide6 离屏 UI 测试 | 24/24 通过 |
| Windows DPAPI 真实加密/解密临时往返 | 通过，文件中无明文测试密码 |
| PyInstaller 构建 | 6.16.0 / Python 3.13 / Windows x64 通过 |
| EXE 文件版本 | 0.3.0 |
| EXE `--self-test` | OCR 模型、ONNX Runtime、DPAPI 全部通过，退出码 0 |
| EXE GUI 冒烟 | 窗口成功启动并显示版本 0.3.0 |

用户此前已确认真实登录、课程选择和课表导出通过。本次发布没有为了测试而退掉真实课程；退课协议使用接口 mock、精确 BJDM 断言、服务器拒绝分支、最终移除复核和双确认 UI 测试覆盖。

## 从源码复现

```powershell
python -m pip install -r requirements-build.txt
python scripts\build_release.py
```

脚本会生成 `release\XDU-Course-Assistant-v0.3.0-windows-x64.exe` 和同名 `.sha256` 文件。
