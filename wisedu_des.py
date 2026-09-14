# 金智(wisedu) 选课系统登录用的 DES 加密：等价于站点前端里的 window.DES.strEncSimple(密码)
#
# 这段实现是从 https://res.xidian.edu.cn/products/yjs/xsxkapp/indexjsp.js 中
# window.DES={strEncSimple:function(B){return d(B,"1","2","3")}, ...} 的实现逐行移植来的。
#
# 注意：它并不是标准 DES！很多人在这里踩坑——用标准 DES 库（pycryptodome / openssl）算出来的
# 密文和站点前端算出来的不一样。原因是这份 JS 的 PC-2（压缩置换表）最后 8 项比标准 DES 少 1：
#   标准 PC-2（0 基）尾段: 34,53,46,42,50,36,29,32
#   这份 JS        尾段: 33,52,45,41,49,35,28,31
# 所以只能用这份移植版。正确性由下面 SELF_TEST 里的实测向量保证（向量取自站点前端 JS 的真实输出）。
#
# 用法：
#   from wisedu_des import str_enc_simple
#   encrypt_password("your-password")   # -> 32/48/... 位十六进制字符串

S_BOXES = (
    ((14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7),
     (0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8),
     (4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0),
     (15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13)),
    ((15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10),
     (3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5),
     (0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15),
     (13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9)),
    ((10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8),
     (13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1),
     (13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7),
     (1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12)),
    ((7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15),
     (13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9),
     (10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4),
     (3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14)),
    ((2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9),
     (14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6),
     (4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14),
     (11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3)),
    ((12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11),
     (10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8),
     (9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6),
     (4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13)),
    ((4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1),
     (13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6),
     (1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2),
     (6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12)),
    ((13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7),
     (1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2),
     (7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8),
     (2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11)),
)

# P 置换
P_TABLE = (15, 6, 19, 20, 28, 11, 27, 16, 0, 14, 22, 25, 4, 17, 30, 9,
           1, 7, 23, 13, 31, 26, 2, 8, 18, 12, 29, 5, 21, 10, 3, 24)
# 末置换（FP）
FP_TABLE = (39, 7, 47, 15, 55, 23, 63, 31, 38, 6, 46, 14, 54, 22, 62, 30,
            37, 5, 45, 13, 53, 21, 61, 29, 36, 4, 44, 12, 52, 20, 60, 28,
            35, 3, 43, 11, 51, 19, 59, 27, 34, 2, 42, 10, 50, 18, 58, 26,
            33, 1, 41, 9, 49, 17, 57, 25, 32, 0, 40, 8, 48, 16, 56, 24)
# 压缩置换（PC-2）——注意这份 JS 的尾段与标准 DES 不同，别替换成标准表
PC2_TABLE = (13, 16, 10, 23, 0, 4, 2, 27, 14, 5, 20, 9, 22, 18, 11, 3,
             25, 7, 15, 6, 26, 19, 12, 1, 40, 51, 30, 36, 46, 54, 29, 39,
             50, 44, 32, 47, 43, 48, 38, 55, 33, 52, 45, 41, 49, 35, 28, 31)
# 每轮左移位数
SHIFTS = (1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1)


def _str_to_bt(text):
    """字符串 -> 64 位数组：每个字符占 16 位（高位在前），不足 4 个字符补 0"""
    bt = [0] * 64
    for i in range(min(4, len(text))):
        code = ord(text[i])
        for j in range(16):
            bt[16 * i + j] = (code >> (15 - j)) & 1
    return bt


def _get_key_bytes(key):
    """密钥串按 4 字符一组转成 64 位数组"""
    out = []
    iterator = len(key) // 4
    for i in range(iterator):
        out.append(_str_to_bt(key[4 * i:4 * i + 4]))
    if len(key) % 4:
        out.append(_str_to_bt(key[4 * iterator:]))
    return out


def _bt64_to_hex(bt):
    return "".join("%X" % int("".join(str(b) for b in bt[4 * i:4 * i + 4]), 2) for i in range(16))


def _init_permute(data):
    """初始置换 IP"""
    out = [0] * 64
    m, n = 1, 0
    for i in range(4):
        k = 0
        for j in range(7, -1, -1):
            out[8 * i + k] = data[8 * j + m]
            out[8 * i + k + 32] = data[8 * j + n]
            k += 1
        m += 2
        n += 2
    return out


def _expand_permute(right):
    """E 扩展"""
    out = [0] * 48
    for i in range(8):
        out[6 * i + 0] = right[31] if i == 0 else right[4 * i - 1]
        out[6 * i + 1] = right[4 * i + 0]
        out[6 * i + 2] = right[4 * i + 1]
        out[6 * i + 3] = right[4 * i + 2]
        out[6 * i + 4] = right[4 * i + 3]
        out[6 * i + 5] = right[0] if i == 7 else right[4 * i + 4]
    return out


def _xor(a, b):
    return [x ^ y for x, y in zip(a, b)]


def _s_box_permute(expand_byte):
    out = [0] * 32
    for m in range(8):
        row = 2 * expand_byte[6 * m + 0] + expand_byte[6 * m + 5]
        col = 8 * expand_byte[6 * m + 1] + 4 * expand_byte[6 * m + 2] \
            + 2 * expand_byte[6 * m + 3] + expand_byte[6 * m + 4]
        val = S_BOXES[m][row][col]
        for i in range(4):
            out[4 * m + i] = (val >> (3 - i)) & 1
    return out


def _p_permute(data):
    return [data[P_TABLE[i]] for i in range(32)]


def _finally_permute(data):
    return [data[FP_TABLE[i]] for i in range(64)]


def _get_sub_keys(key_byte):
    """PC-1 选位 + 循环左移 + PC-2，得到 16 个 48 位子密钥"""
    key = [0] * 56
    for e in range(7):
        for j in range(8):
            key[8 * e + j] = key_byte[8 * (7 - j) + e]
    keys = []
    for i in range(16):
        for _ in range(SHIFTS[i]):
            first, second = key[0], key[28]
            for k in range(27):
                key[k] = key[k + 1]
                key[28 + k] = key[29 + k]
            key[27] = first
            key[55] = second
        keys.append([key[idx] for idx in PC2_TABLE])
    return keys


def _enc(data, key):
    """一轮 DES（对应 JS 里的 e()）"""
    keys = _get_sub_keys(key)
    ip = _init_permute(data)
    left, right = ip[:32], ip[32:]
    for i in range(16):
        previous_left = left[:]
        left = right[:]
        right = _xor(_p_permute(_s_box_permute(_xor(_expand_permute(right), keys[i]))), previous_left)
    return _finally_permute(right + left)


def str_enc(data, first_key="", second_key="", third_key=""):
    """对应 JS 的 DES.strEnc(data, k1, k2, k3)：每 4 个字符一块，依次用各密钥加密，输出十六进制"""
    out = ""
    first = _get_key_bytes(first_key) if first_key else None
    second = _get_key_bytes(second_key) if second_key else None
    third = _get_key_bytes(third_key) if third_key else None

    def _once(block):
        cur = block
        if first:
            for k in first:
                cur = _enc(cur, k)
        if second:
            for k in second:
                cur = _enc(cur, k)
        if third:
            for k in third:
                cur = _enc(cur, k)
        return _bt64_to_hex(cur)

    total = len(data)
    if total == 0:
        return out
    if total < 4:
        return _once(_str_to_bt(data))
    iterator = total // 4
    for i in range(iterator):
        out += _once(_str_to_bt(data[4 * i:4 * i + 4]))
    if total % 4:
        out += _once(_str_to_bt(data[4 * iterator:]))
    return out


def str_enc_simple(data):
    """站点前端登录时用的就是这个：DES.strEncSimple(密码) == strEnc(密码, "1", "2", "3")"""
    return str_enc(data, "1", "2", "3")


def encrypt_password(password):
    """给登录接口用的 loginPwd 字段"""
    return str_enc_simple(password)


# 实测向量（由站点前端 indexjsp.js 用 node 跑出来的真实结果，改动本文件后请重跑校验）
SELF_TEST = {
    "1": "FF175F03E46ADFCE",
    "12": "514F4FFCD4A12D55",
    "123": "2120D46C30DA4DB2",
    "1234": "C1BB5938DF9F2190",
    "12345": "C1BB5938DF9F21906A38D8589DAA34ED",
    "123456": "C1BB5938DF9F21908D35C1455E2F4800",
    "abc123": "4860B1E277464DB1C804E426A2405196",
    "a": "A62B4F77D5F8C6C7",
    "Mvp3046058037": "2A1FCE662CC09086687496A99419942C1FF35483F1E0B8DC83A81CD2BE7DA273",
}

if __name__ == "__main__":
    bad = 0
    for text, expect in SELF_TEST.items():
        got = str_enc_simple(text)
        flag = "OK " if got == expect else "FAIL"
        if got != expect:
            bad += 1
        print(f"[{flag}] {text!r:18s} -> {got}  (期望 {expect})")
    print("全部通过" if not bad else f"{bad} 个不一致")
