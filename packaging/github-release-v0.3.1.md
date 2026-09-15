## XDU Course Assistant v0.3.1

这是 v0.3.0 的体积优化版本，业务功能与安全边界不变。

GitHub Actions 发布附件为 `66,621,741` 字节（`63.54 MiB`），较 v0.3.0 的 `189.74 MiB` 减少 `66.51%`；SHA-256 为 `858cd08a58d55ad5bd2c66b569431a3bb0cfede665f0425ce640774f4f53e0d7`。本地 Python 3.13.0 干净环境参考构建为 `62.49 MiB`；与发布附件的差异来自 Actions 构建机的 Python 补丁版本等环境因素。

### 主要变化

- 发布包只保留 ddddocr 实际使用的 `common_old.onnx` OCR 分类模型。
- 从 EXE 排除未使用的 OpenCV、beta/目标检测模型、Pillow 非 JPEG 插件。
- 桌面运行时改用 PySide6 Essentials，并裁剪 QML、Quick、PDF、SVG、QtNetwork、翻译和非必要插件。
- 排除 requests 的可选 PyOpenSSL/cryptography 链路，HTTPS 继续使用 Python 标准库 SSL。
- 保留 `opengl32sw.dll`，兼顾无 GPU、远程桌面和显卡驱动异常环境。
- 发布自检现在会执行内置 JPEG 的真实 OCR 分类，不再只检查模型初始化。
- 构建后自动审计 EXE 归档，发现已禁用组件或缺少必要成员时直接失败。
- ddddocr 的分类路径在没有 OpenCV 的环境中通过 fail-closed 兼容层运行；任何误用 OpenCV 专属 API 都会立即报错。

### 安全与功能

- 保存密码仍为可选功能，并使用当前 Windows 用户的 DPAPI 加密。
- 退课仍要求连续两次确认，并按精确 BJDM 提交及最终复核。
- 登录、自动选课、已选课程查询、CSV 导出和 CLI 行为保持不变。
- 项目来源与致谢见仓库 `NOTICE.md`。
- 本地验证通过 25 项测试、学校 HTTPS 登录页/验证码接口、实时验证码 JPEG OCR、打包后 OCR/DPAPI、自检失败报告、PE 版本、GUI 子进程启动、归档审计和 SHA-256 校验。

### 校验

下载 EXE 和同名 `.sha256` 文件后，可运行：

```powershell
Get-FileHash .\XDU-Course-Assistant-v0.3.1-windows-x64.exe -Algorithm SHA256
.\XDU-Course-Assistant-v0.3.1-windows-x64.exe --self-test
```
