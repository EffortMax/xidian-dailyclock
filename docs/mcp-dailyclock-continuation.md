# DailyClock 续作审计与实现记录

日期：2026-09-15

## 输入与范围

本轮以仓库内的 `开发记录与交接.md` 为主要工作记录，并核对当前 `main` 分支中的桌面应用提交。续作范围选择交接文档优先级最高且能够离线验证的部分：多目标抢课、日志轮转，以及桌面人工验证码可用性。

未执行真实选课或退课请求；所有会改变选课结果的路径只做 mock 验证。

## 基线

- Git 工作树在本轮开始时无已跟踪文件改动；`tools/` 为本地未跟踪工具目录。
- 初始测试：8 项通过。
- 初始编辑器诊断：0 个 error / warning。

## 设计决策

### 多目标编排

`app/services/course_service.py` 的 `auto_select_many` 维护待处理目标集合。每轮只拉取一次课程列表，再按目标独立筛选。成功目标只有在“已选课程”复核命中后才会从集合移除。

同一 KCDM 不允许在一个批次中重复出现，避免同轮对同一课程的不同教学班发送多个提交请求。

空结果策略：

- `warn`：保留严格条件并继续轮询。
- `ignore_filter`：放宽教学班名称与校区，但显式 BJDM 锁定永不放宽。
- `abort`：立即终止批次，避免筛选错误导致误选。

单目标入口 `auto_select` 委托给同一多目标引擎，避免两套选课语义分叉。

### 人工验证码

工作线程通过 `CaptchaBridge` 向 Qt 主线程发送验证码图片和同步请求；主线程显示输入对话框并把结果返回工作线程。这样关闭 OCR 后不再依赖隐藏的终端 stdin。

### 日志轮转

`TeeLogger` 在打开文件前和每次写入前检查文件大小。达到阈值后按 `.1` 到 `.N` 轮转，默认阈值 1,000,000 字节、备份 5 份；配置为 0 时关闭轮转。

## 变更文件

- `app/models.py`
- `app/main.py`
- `app/services/auth_service.py`
- `app/services/course_service.py`
- `courseChoose.py`
- `config.example.py`
- `README.md`
- `.gitignore`
- `开发记录与交接.md`
- `tests/test_app_models.py`
- `tests/test_service_imports.py`
- `tests/test_ui_smoke.py`
- `tests/test_logging.py`

## 验证结论

- 单元与 UI 离屏测试：15 项通过。
- 编辑器诊断：0 个 error / warning。
- 多目标测试确认两个目标共用一次课程列表请求，并分别完成最终已选复核。
- 日志测试覆盖启动前轮转与运行中轮转。

## 剩余风险

- 真实选课系统有时间窗口、排队与会话限制，多目标流程需要在合法、可控的真实窗口做一次人工监督验证。
- 人工验证码弹窗需要在 Windows 正常图形环境再做一次交互确认。
- 退课仍未进行真实破坏性验证。
- “全部课程”接口对应的提交 `lx` 仍未确认，因此没有接入。

## v0.3.0 发布续作

在上述续作基础上继续完成：

- 登录页 opt-in 凭据保存，密码使用 Windows DPAPI；真实 DPAPI 往返验证通过。
- 桌面精确 BJDM 退课、连续两次 UI 确认，以及服务端成功后的最终移除复核。
- 测试增至 24 项，新增凭据静态文件、退课成功/拒绝/复核失败和双确认 UI 覆盖。
- PyInstaller 6.16.0 单文件 Windows x64 构建，内含 PySide6、ddddocr 模型和 ONNX Runtime。
- 发布包 `--self-test` 与 GUI 窗口启动冒烟均通过。
- 本轮没有执行真实退课；真实登录、选课和课表导出采用用户此前确认通过的结果。

发布文件、校验值与复现命令见 `docs/release-v0.3.0.md`。
