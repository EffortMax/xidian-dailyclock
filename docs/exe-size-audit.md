# Windows EXE 体积与依赖审计

审计日期：2026-09-15
基线对象：本地 v0.3.0 单文件构建（`198,955,776` 字节，`189.74 MiB`）
实施对象：本地 v0.3.1 干净环境构建（`65,521,203` 字节，`62.49 MiB`）
状态：**已按 Review 结论实施，通过本地和 GitHub Actions 独立验证并发布 v0.3.1；v0.3.0 发布物未被覆盖。**

## 0. v0.3.1 实施结果

- 减少 `133,434,573` 字节（`127.25 MiB`），相对基线缩小 `67.07%`。
- 本地验证产物 SHA-256：`24fbe5fe9621f5a182ad8a0281f650d772b74ce40b6fab592fe9ee2f78fa4453c`。
- GitHub Actions 发布附件为 `66,621,741` 字节（`63.54 MiB`），相对基线减少 `132,334,035` 字节（`126.20 MiB`，`66.51%`）；SHA-256 为 `858cd08a58d55ad5bd2c66b569431a3bb0cfede665f0425ce640774f4f53e0d7`。
- 发布工作流 [34949041791](https://github.com/EffortMax/xidian-dailyclock/actions/runs/34949041791) 在提交 `a2c360ca52d90446d3c69941e3da92d3e522214a` 上成功；Release 与轻量 tag `v0.3.1` 均指向该提交。
- 专用 Python 3.13 环境 `D:\newproject\.venv-xdu-031` 仅按 `requirements-build.txt` 和 `scripts/install_build_dependencies.py` 安装；`cv2` 确认不存在，ddddocr 1.6.1 通过 `--no-deps` 固定安装。
- 归档审计覆盖 80 个顶层 CArchive 成员及 470 个 PYZ 模块，确认没有禁用成员。
- 保留：`common_old.onnx`、ONNX Runtime、Pillow `_imaging`、Qt Core/Gui/Widgets、`qwindows.dll`、`qjpeg.dll`、`qmodernwindowsstyle.dll`、`opengl32sw.dll`，以及标准库 HTTPS 使用的 `_ssl.pyd`、`libssl-3.dll`、`libcrypto-3.dll`。
- 排除：`common.onnx`、`common_det.onnx`、OpenCV、cryptography/cffi/PyOpenSSL、Pillow AVIF/WebP/CMS/ImageMath/Tk 扩展、Qt Network/OpenGL/PDF/QML/Quick/SVG/VirtualKeyboard、翻译及非必要插件。
- 验证通过：编译、25 项单元/UI 测试、无 OpenCV 的内置 JPEG OCR `1234`、Windows DPAPI、实时学校 HTTPS 登录页/验证码 token/验证码 JPEG 与 OCR、打包后 OCR/DPAPI、自检失败报告、PE 版本 `0.3.1`、子进程感知 GUI 启动、归档审计及 SHA-256 校验。

## 1. 审计方法与结论边界

本次交叉检查了：

1. 维护中运行链路的 Python AST 导入（`run_app.py`、`app/`、`xidian_login.py`、`courseChoose.py`、`courseQuery.py`、`wisedu_des.py`）。
2. `requirements.txt`、`requirements-build.txt` 与 `packaging/windows.spec`。
3. 本地虚拟环境的 distribution metadata 和依赖声明。
4. `build/windows/Analysis-00.toc`、`xref-windows.html` 与本地 EXE 的 PyInstaller CArchive 目录。
5. ddddocr 1.6.1 的实际导入图、构造参数和模型选择逻辑。

下文“压缩占用”来自本地 v0.3.0 EXE 的 CArchive 条目，是比 site-packages 目录大小更接近最终 EXE 的估算。它不等于删除后的精确净缩减量；模块之间可能存在共享 DLL 或连带依赖，最终结果必须以重建后的 EXE 为准。

## 2. 当前真正需要的运行依赖

项目源码直接使用的第三方包只有：

- `requests`：登录、选课及课表 HTTP 会话。
- `PySide6.QtCore`、`PySide6.QtGui`、`PySide6.QtWidgets`：桌面界面和验证码图片显示。
- `ddddocr`：无人值守验证码分类识别。

必须保留的主要传递依赖：

- `requests` 链路：`certifi`、`charset-normalizer`、`idna`、`urllib3`。
- ddddocr OCR 分类链路：`numpy`、`onnxruntime`、`Pillow`。
- Qt Widgets 链路：`PySide6_Essentials`、`shiboken6`，以及 `Qt6Core`、`Qt6Gui`、`Qt6Widgets`、Windows 平台插件 `qwindows.dll`。
- OCR 模型：当前 ddddocr 1.6.1 的 `DdddOcr(show_ad=False)` 默认实际加载 `common_old.onnx`；本项目的两个实例均未启用 `det`、`beta` 或自定义模型。

构建环境还需要 `pyinstaller`、`altgraph`、`packaging`、`pefile`、`pyinstaller-hooks-contrib`、`pywin32-ctypes` 和 `setuptools`，但这些构建工具本身不是应用运行依赖。

## 3. 已进入 EXE、但当前功能路径不使用的候选项

### 3.1 第一批候选：收益高，建议优先做隔离构建验证

| 候选项 | 本地 EXE 压缩占用 | 判定依据 | 建议动作与风险 |
| --- | ---: | --- | --- |
| `ddddocr/common.onnx` | `47.97 MiB` | 只有 `beta=True` 才会选择；项目从未传入该参数 | spec 仅收集 `common_old.onnx`。必须固定 ddddocr 版本，并增加真实图片 `classification()` 自检，防止上游默认逻辑变化 |
| `ddddocr/common_det.onnx` | `17.81 MiB` | 仅目标检测 `det=True` 使用；项目只做验证码分类 | 从 datas 排除；保留自动化 OCR 分类测试 |
| `opencv-python` / `cv2` | `36.61 MiB` | 项目只调用 Pillow/NumPy/ONNX 分类链路；ddddocr 1.6.1 的预处理、检测模块虽未被调用，却会在包导入时提前探测 `cv2` | 在 PyInstaller bundle 中排除 `cv2`，并在导入 ddddocr 前安装只允许导入、访问任意 OpenCV API 即报错的兼容 stub；真实 JPEG `classification()` 自检负责证明受支持链路。注意 ddddocr 的 Windows metadata 仍把 `opencv-python` 声明为硬依赖 |
| Pillow 非 JPEG 插件：`_avif`、`_webp`、`_imagingcms`、`_imagingmath`、`_imagingtk` | 约 `4.46 MiB` | 项目只将学校返回的 JPEG 验证码交给 PIL/Qt；不处理 AVIF、WebP、ICC、ImageMath 或 Tk | bundle 中排除这些扩展，保留 Pillow `_imaging`；用真实 JPEG 验证码做打包后 OCR 测试 |
| `cryptography`、`cffi`、`libcrypto-3-x64.dll`、`libssl-3-x64.dll` 及其 runtime hook | 约 `5.98 MiB` | 由 `requests`/`urllib3.contrib.pyopenssl` 的可选分支被静态分析带入；项目 HTTPS 走 Python 标准库 `ssl`，密码提交使用纯 Python 站点算法，凭据加密使用 Windows DPAPI/ctypes | 排除 optional PyOpenSSL 链路，并实测所有 HTTPS 接口。不能删除 Python `_ssl` 使用的 `libssl-3.dll`、`libcrypto-3.dll` |

仅以上五组在当前归档中的理论压缩占用合计约 `112.83 MiB`。这是候选条目占用之和，不是承诺的最终净缩减值。

### 3.2 第二批候选：Qt 插件和 Addons 闭包

源码只使用 QtCore、QtGui、QtWidgets，但当前归档还包含以下内容：

| 候选组 | 本地 EXE 压缩占用 | 说明 |
| --- | ---: | --- |
| `Qt6Quick`、`Qt6Qml*`、`Qt6Pdf`、`Qt6OpenGL`、`Qt6Svg`、`Qt6VirtualKeyboard`、`Qt6Network`、`QtNetwork.pyd` | 约 `9.44 MiB` | 项目没有 QML、Quick、PDF、SVG、QtNetwork 或虚拟键盘代码；主要由 Addons 和插件依赖闭包带入 |
| 96 个 Qt 翻译文件 | 约 `1.85 MiB` | 项目没有安装 `QTranslator`；当前 UI 文本由应用自身提供 |
| `qdirect2d.dll`、`qminimal.dll`、`qoffscreen.dll` | 约 `0.51 MiB` | 正常发布只需要 Windows `qwindows.dll`；离屏测试在源码测试阶段执行，不要求发布 EXE 带 `qoffscreen.dll` |
| 除 `qjpeg.dll` 外的 Qt 图片插件 | 约 `0.57 MiB` | 当前只显示 JPEG 验证码；GIF、ICNS、ICO、PDF、SVG、TGA、TIFF、WBMP、WebP 未使用 |
| Qt TLS、触摸、SVG icon、网络信息、虚拟键盘插件 | 约 `0.40 MiB` | 网络访问由 requests 完成，应用没有对应 Qt 功能 |

建议将运行依赖从 `PySide6` 元包评估为 `PySide6_Essentials`，并在 spec 中显式保留 `Qt6Core`、`Qt6Gui`、`Qt6Widgets`、`qwindows.dll`、`qjpeg.dll` 和必要的 MSVC runtime。上述 Qt 候选合计约 `12.77 MiB`，必须通过正常 GUI 启动、验证码弹窗、文件对话框、双确认对话框和 CSV 导出验证后才能删除。

`PySide6/opengl32sw.dll` 另占约 `7.31 MiB`，源码没有 OpenGL 功能，但它是 Qt 在无可用 GPU/驱动异常时的软件渲染回退。**不建议在第一轮直接删除**；应先在虚拟机、远程桌面和禁用硬件加速环境中测试。

### 3.3 第三批候选：收益低，最后处理

- `PyYAML`：归档中 `_yaml` 扩展约 `0.10 MiB`，Python 部分位于共享 PYZ；由 `numpy.__config__` 的可选展示路径带入，业务不读取 YAML。
- `numpy.f2py`、`numpy.testing` 和部分开发辅助模块：验证码推理不调用；Python 模块位于共享 PYZ，收益预计较小。不能删除 NumPy 核心、`_multiarray_umath` 或其 OpenBLAS DLL，否则 NumPy/ONNX Runtime 可能无法导入。
- `threadpoolctl`：当前静态分析可见但业务没有直接调用；体积很小，需确认 onnxruntime/numpy 导入后再决定。
- ddddocr 包内 `README.md`、`logo.png`：合计只有约 `0.02 MiB`，可随模型 datas 精确化一并去除。

## 4. 虚拟环境中与本项目无关、且未进入当前 EXE 的包

当前使用的是共享环境 `D:\newproject\.venv`，其中存在大量其它任务安装的包。以下包没有在当前 EXE 的模块或二进制目录中找到对应顶层模块，也不属于本项目声明的直接依赖或必要构建链路，可视为本项目环境污染项：

- Google/LLM：`google-ai-generativelanguage`、`google-api-core`、`google-api-python-client`、`google-auth`、`google-auth-httplib2`、`google-generativeai`、`googleapis-common-protos`、`langchain-core`、`langchain-protocol`、`langchain-text-splitters`、`langsmith`、`proto-plus`。
- 数据科学/绘图：`contourpy`、`cycler`、`fonttools`、`joblib`、`kiwisolver`、`matplotlib`、`pandas`、`scikit-learn`、`scipy`、`seaborn`、`pyparsing`、`python-dateutil`、`tzdata`。
- 浏览器/异步 HTTP：`chromium`、`playwright`、`pyee`、`greenlet`、`anyio`、`h11`、`httpcore`、`httpx`。
- Office/XML：`openpyxl`、`et_xmlfile`、`lxml`。
- 其它无关工具链：`Naked`、`aes`、`colorama`、`grpcio`、`grpcio-status`、`httplib2`、`jsonpatch`、`jsonpointer`、`orjson`、`pyasn1`、`pyasn1_modules`、`pycryptodome`、`pydantic`、`pydantic_core`、`annotated-types`、`requests-toolbelt`、`shellescape`、`six`、`tenacity`、`tqdm`、`typing-inspection`、`uritemplate`、`uuid_utils`、`xxhash`、`zstandard`。

以下包虽未作为顶层模块进入归档，但属于声明的传递依赖、包管理或 PyInstaller 构建链路，不列入无关删除清单：`flatbuffers`、`protobuf`、`packaging`、`altgraph`、`pefile`、`pyinstaller`、`pyinstaller-hooks-contrib`、`pywin32-ctypes`、`setuptools`、`pip`。

**不要在共享 `D:\newproject\.venv` 中批量卸载上述包。** 推荐为本项目建立全新的专用构建环境，从 `requirements-build.txt` 安装后再做 spec 排除；这既能避免影响其它项目，也能证明构建不依赖环境偶然状态。未进入当前归档的环境污染包本身不会降低现有 EXE 体积，清理它们的主要价值是可重复构建和审计清晰度。

## 5. 已完成的实施顺序

1. 建立全新专用 Windows 构建虚拟环境并固定运行/构建依赖。
2. 将 self-test 从“模型可初始化”增强为内置 JPEG 的真实 `classification()`，并让 windowed EXE 在失败时输出诊断报告。
3. spec 仅收集 `common_old.onnx`，排除另外两个模型；用 fail-closed cv2 兼容层支持分类链路而不打包 OpenCV。
4. 排除 Pillow 非 JPEG 扩展和 optional cryptography/PyOpenSSL 链路，同时保留并审计标准库 SSL。
5. 改用 `PySide6_Essentials`，逐项缩减 Qt Addons、插件及翻译；首轮按 Review 决定保留 `opengl32sw.dll`。
6. 在源码与打包后完成 OCR、DPAPI、HTTPS、25 项测试、GUI 子进程、归档及校验和验证。
7. 使用独立 v0.3.1 版本和 GitHub Actions 发布，不覆盖 v0.3.0。
