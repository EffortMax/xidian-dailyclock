"""启动西电研究生选课桌面应用。"""

try:
    from app.main import main
except ModuleNotFoundError as exc:
    if exc.name and exc.name.startswith("PySide6"):
        raise SystemExit(
            "缺少桌面依赖 PySide6，请执行：python -m pip install -r requirements.txt"
        ) from exc
    raise


if __name__ == "__main__":
    raise SystemExit(main())
