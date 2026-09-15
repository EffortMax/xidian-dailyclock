# 西电研究生选课助手

面向西安电子科技大学研究生选课系统的桌面与命令行客户端。项目已经适配 2026 年现行登录、课程列表、两阶段选课结果轮询、已选课程复核与课表接口。

> 本项目仅供个人学习和接口兼容性研究。请遵守学校系统规则，合理设置轮询间隔，并自行承担使用风险。

## 功能

- PySide6 桌面应用：登录、课程查询、多目标自动选课、课表 CSV 导出。
- 登录页可选择保存账户和密码；密码使用当前 Windows 用户的 DPAPI 加密，默认不保存。
- 桌面端可按精确 BJDM 退掉已选课程；提交前必须连续确认两次，提交后还会复核课程已移除。
- 验证码支持 ddddocr 无人值守识别，也支持桌面弹窗人工输入。
- 多目标任务每轮只拉取一次课程列表，各目标保留独立的课程代码、教学班、校区和空结果策略。
- 选课只有在两阶段接口完成且“已选课程”复核成功后才会报告成功。
- 会话过期、异常页及瞬时网络故障可以自动恢复或重试。
- 命令行日志按大小自动轮转，默认单文件 1 MB，保留 5 份历史文件。
- 课表以 UTF-8 BOM CSV 导出，可用于 Excel 或 WakeUp 课程表。

## 直接使用 Windows EXE

从 GitHub [Releases](https://github.com/EffortMax/xidian-dailyclock/releases) 下载：

- `XDU-Course-Assistant-v0.3.0-windows-x64.exe`
- 同名 `.sha256` 校验文件

EXE 是包含 PySide6、ddddocr、ONNX 模型与运行时的 Windows x64 单文件版本，不需要预装 Python。单文件程序首次启动需要解压依赖，可能等待数秒；Windows SmartScreen 若提示未知发布者，请先核对下载来源和 SHA-256。

```powershell
Get-FileHash .\XDU-Course-Assistant-v0.3.0-windows-x64.exe -Algorithm SHA256
.\XDU-Course-Assistant-v0.3.0-windows-x64.exe
```

发布包还提供无网络、无选课副作用的依赖自检：

```powershell
.\XDU-Course-Assistant-v0.3.0-windows-x64.exe --self-test
$LASTEXITCODE  # 0 表示 OCR 模型、ONNX Runtime 与 Windows DPAPI 均通过
```

## 从源码安装与启动

推荐使用项目虚拟环境，并确保安装与运行使用同一个 Python 解释器：

```powershell
$py = "D:\xxx\.venv\Scripts\python.exe" (找到自己python的解释器路径)
& $py -m pip install -r requirements.txt
& $py run_app.py
```

桌面应用包含三个工作页：

1. **登录**：填写学号和密码；默认启用 OCR。关闭“无人值守”后，验证码会在应用内弹窗显示。需要时可主动勾选 DPAPI 加密保存。
2. **选课 / 自动抢课**：先查询课程或手工填写筛选条件，再把一个或多个目标加入队列；“查看已选课程”后可选择一行退课。
3. **课表导出**：选择 CSV 路径，可按学期过滤并决定是否包含无固定排课课程。

### 保存账户和密码

- 该选项默认关闭；只有勾选并成功登录后才写入凭据文件。
- 账户标识与 DPAPI 密文保存在 `%LOCALAPPDATA%\DailyClockXDU\credentials.json`，不会写入明文密码。
- 密文绑定当前 Windows 用户，复制到另一账户或另一台电脑后不能解密。
- 要清除凭据，可取消勾选后成功登录一次，或在应用关闭时手工删除上述文件。

### 桌面退课

1. 点击“查看已选课程”。
2. 选中要退掉的课程行并点击“退掉选中课程”。
3. 通过第一次课程信息确认。
4. 阅读不可逆风险提示并通过第二次确认。

任意一次选择“否”都不会创建后台退课任务。服务层只提交选中行的精确 BJDM；接口返回成功后，会再次读取已选课程并确认该 BJDM 已消失，否则仍按失败报告。

### 多目标空结果策略

每个目标可以单独设置：

- `warn`（警告并继续）：保持筛选条件，后续轮次继续等待。
- `ignore_filter`（放宽筛选）：严格条件无结果时，只保留课程代码并尝试其它教学班/校区；如果明确锁定了 BJDM，则不会放宽。
- `abort`（停止）：目标无匹配教学班时立即停止整批任务，适合防止误选。

建议优先通过课程查询结果锁定 BJDM；自动选课开始前应用还会进行一次确认。
同一课程代码只能加入队列一次；如果要限制教学班或校区，应在该目标自己的筛选条件中设置。

## 命令行模式

复制模板并填写本地配置：

```powershell
Copy-Item config.example.py config.py
```

`config.py` 已被 Git 忽略，不得提交或外传。常用命令：

```powershell
python courseChoose.py                         # 按 config.py 运行单目标自动选课
python courseChoose.py --list                  # 查看可选课程
python courseChoose.py --list 英语 --xq 南校区
python courseChoose.py --list --chosen         # 查看已选课程
python courseChoose.py --drop X1TE9015         # 退课，默认需要再次确认
python courseQuery.py --all                    # 导出课表，包含线上课
python xidian_login.py --unattended --diagnose # 登录与接口诊断
python wisedu_des.py                            # 密码加密向量自检
```

日志配置位于 `config.py`：

```python
log_file = "courseChoose.log"
log_max_bytes = 1_000_000
log_backup_count = 5
```

轮转文件依次为 `courseChoose.log.1`、`.2` 等。把 `log_max_bytes` 设为 `0` 可以关闭轮转。

## 本地数据与安全

- 桌面应用 Cookie 默认保存在 `%LOCALAPPDATA%\DailyClockXDU\cookies.json`。
- 只有主动勾选“保存账户和密码”时，桌面应用才创建 `credentials.json`；密码字段是 Windows DPAPI 密文，不是明文。
- 密码在应用运行期间仍会在内存中保留，以便会话恢复。DPAPI 只能降低静态文件泄露风险，不能防止已控制当前 Windows 会话的恶意程序读取数据。
- CLI 的 `config.py` 仍是本地明文配置；如使用 CLI，必须限制文件权限并禁止外传。
- CLI 的 `config.py`、`cookies.json`、验证码、CSV 与日志均已加入 `.gitignore`。
- Cookie 等同登录凭据，请勿上传、截图或发送给他人。

## 验证

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest discover -s tests -v
```

当前版本 24 项测试覆盖模型校验、DPAPI 凭据文件、精确 BJDM 退课及最终复核、桌面两次确认、单/多目标选课编排、每轮课程列表复用、筛选放宽策略、日志轮转、课表导出和 UI 冒烟。

复现 Windows 发布包：

```powershell
python -m pip install -r requirements-build.txt
python scripts\build_release.py
```

产物和校验文件写入 `release\`。正式 v0.3.0 的构建与验证明细见 [`docs/release-v0.3.0.md`](docs/release-v0.3.0.md)。

## 代码结构

- `app/main.py`：桌面界面、后台任务和人工验证码桥接。
- `app/services/`：登录、选课与课表服务层。
- `app/models.py`：课程与自动选课目标模型。
- `courseChoose.py`：现行选课协议及 CLI。
- `courseQuery.py`：课表读取与 CSV 解析。
- `xidian_login.py`：登录、Cookie 和会话恢复。
- `wisedu_des.py`：与站点 JavaScript 一致的密码加密实现。
- `packaging/windows.spec`、`scripts/build_release.py`：可复现的 Windows 单文件发布配置。
- `开发记录与交接.md`：接口调研、已知风险与维护手册。

## 已知限制

- OCR 识别并非 100% 准确，代码会自动更换验证码重试。
- 会话可能被其它设备登录挤掉；无人值守期间不建议重复登录同一账号。
- 当前只接入四类已确认 `lx` 语义的课程来源。
- 退课接口与双确认已做自动化和发布包验证，但尚未用真实课程做破坏性验证。
- `clock.py`、`utils.py` 和 `test.py` 是原仓库历史代码，接口已经失效，不属于当前选课助手运行链路。
