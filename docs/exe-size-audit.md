# Windows EXE 体积与依赖审计（Review 草案）

审计日期：2026-09-15
审计对象：本地 v0.3.0 单文件构建（`198,955,776` 字节，约 `189.74 MiB`）
状态：**仅形成候选清单，尚未修改 requirements、PyInstaller spec 或发布物。**

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
| `opencv-python` / `cv2` | `36.61 MiB` | 维护中源码没有导入；ddddocr 1.6.1 只在 `utils.exceptions.safe_import_opencv()` 的诊断辅助函数中延迟导入，当前 OCR 分类链路不调用 | 在 PyInstaller bundle 中排除 `cv2`。注意 ddddocr 的 Windows metadata 仍把 `opencv-python` 声明为硬依赖，不能仅在普通源码环境中直接卸载后就宣称受支持 |
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

## 5. Review 后建议的实施顺序

1. 建立全新专用 Windows 构建虚拟环境，记录完整 `pip freeze`。
2. 固定 ddddocr 版本；将 self-test 从“模型可初始化”增强为“内置 JPEG 样本可完成 classification”。
3. spec 只收集 `common_old.onnx`，排除另外两个模型和 cv2，先完成第一版对比构建。
4. 排除 Pillow 非 JPEG 插件及 optional cryptography/PyOpenSSL 链路，验证真实 HTTPS 登录与验证码 OCR。
5. 将 PySide6 元包评估为 Essentials，并逐项缩减 Qt Addons 和插件。
6. 每一步记录 EXE 大小、归档清单和 SHA-256；运行 24 项测试、打包 self-test、GUI 子进程启动、两次确认 UI、CSV 导出和受控真实登录。
7. `opengl32sw.dll` 单独作为兼容性实验，不与第一批高置信度删除合并。

完成 Review 前不应覆盖现有 v0.3.0 Release；优化版本建议使用新的版本号和独立 GitHub Actions 构建记录。
