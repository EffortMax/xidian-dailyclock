"""西电研究生选课桌面应用。"""

import os


__version__ = "0.3.1"


# 通过服务层导入旧协议模块时，不读取项目根目录的明文 config.py。
os.environ.setdefault("XDU_LIBRARY_MODE", "1")
