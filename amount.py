# coding: utf-8
"""
输出内容格式:
从同目录 .env 文件读取 API_KEY 和 API_SECRET，并执行原逻辑

=== 正在获取合约 CL_USDT 的最大杠杆限制 ===
状态码: 400
响应: {'label': 'LEVERAGE_EXCEEDED', 'message': 'limit [1, 100]'}

从错误信息中提取的最大杠杆: 100

正在获取可用保证金...
可用保证金: 196.63528496 USDT

    最大杠杆 |           最大开仓(USDT) | 计算公式
----------------------------------------------------------------------
     100 |       17098.72043095 | 196.6353 / (1/100 + 2*0.00075)

建议仓位价值 (max_open 的 1%): 170.99 USDT


[信息] requests 会话已关闭（连接已断开）
"""
import os
import sys
import time
import hashlib
import hmac
import requests
import argparse
import re

# =========================== 配置区 ===========================

FEE_RATE = 0.00075          # 交易费率（如 0.075%）
HOST = "https://api.gateio.ws"
PREFIX = "/api/v4"
DEFAULT_CONTRACT = "CL_USDT"
# =============================================================

# ========== 从 .env 加载 API 密钥 ==========
def load_env():
    """读取同目录下的 .env 文件，返回 key-value 字典"""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if not os.path.exists(env_path):
        print(f"错误: 未找到 .env 文件 (路径: {env_path})")
        sys.exit(1)

    env_vars = {}
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    return env_vars

env_data = load_env()
API_KEY = env_data.get('API_KEY')
API_SECRET = env_data.get('API_SECRET')

if not API_KEY or not API_SECRET:
    print("错误: .env 文件中必须包含 API_KEY 和 API_SECRET")
    sys.exit(1)

def gen_sign(method, url, query_string=None, payload_string=None):
    """生成 Gate.io API 签名头"""
    t = time.time()
    m = hashlib.sha512()
    m.update((payload_string or "").encode('utf-8'))
    hashed_payload = m.hexdigest()
    s = '%s\n%s\n%s\n%s\n%s' % (method, url, query_string or "", hashed_payload, t)
    sign = hmac.new(API_SECRET.encode('utf-8'), s.encode('utf-8'), hashlib.sha512).hexdigest()
    return {'KEY': API_KEY, 'Timestamp': str(t), 'SIGN': sign}


def parse_max_leverage_from_q_multiplier(message):
    """
    从 q_multiplier 的输出中提取最大杠杆。

    支持字典或字符串输入，例如：
    {'leverage_max': '200'}

    为兼容原有调用，也支持 Gate 错误信息：
    limit [1, 100]
    """
    if message is None:
        return None

    if isinstance(message, dict):
        value = message.get('leverage_max')
    else:
        text = str(message)
        match = re.search(
            r"['\"]leverage_max['\"]\s*:\s*['\"]?([0-9]+(?:\.[0-9]+)?)",
            text,
            re.IGNORECASE,
        )
        if match:
            value = match.group(1)
        else:
            # 兼容原有的 LEVERAGE_EXCEEDED 返回值：limit [1, 100]
            match = re.search(
                r"\blimit\s*\[\s*[0-9]+(?:\.[0-9]+)?\s*,\s*"
                r"([0-9]+(?:\.[0-9]+)?)\s*\]",
                text,
                re.IGNORECASE,
            )
            if not match:
                return None
            value = match.group(1)

    try:
        leverage = float(value)
    except (TypeError, ValueError):
        return None

    if leverage <= 0 or not leverage.is_integer():
        return None
    return int(leverage)


def get_max_leverage(session, contract_name):
    """从公开合约信息接口读取合约允许的最大杠杆。"""
    url = f'/futures/usdt/contracts/{contract_name}'
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    resp = session.get(
        HOST + PREFIX + url,
        headers=headers,
        timeout=15,
    )

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError(
            f"获取 {contract_name} 最大杠杆失败: "
            f"HTTP {resp.status_code} {resp.text}"
        ) from exc

    if not resp.ok:
        raise RuntimeError(
            f"获取 {contract_name} 最大杠杆失败: "
            f"HTTP {resp.status_code} {data}"
        )

    max_leverage = parse_max_leverage_from_q_multiplier(data)
    if max_leverage is None:
        raise RuntimeError(f"{contract_name} 的合约信息缺少 leverage_max: {data}")
    return max_leverage


def get_total_available_margin(session):
    """获取统一账户的可用保证金总额"""
    url = '/unified/accounts'
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    sign_headers = gen_sign('GET', PREFIX + url, '')
    headers.update(sign_headers)
    resp = session.get(HOST + PREFIX + url, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return float(data.get('total_available_margin', 0.0))


def compute_max_open(available_margin, max_leverage, fee_rate):
    """使用从错误信息中提取的最大杠杆计算最大可开仓价值（USDT）"""
    denominator = 1.0 / max_leverage + 2 * fee_rate
    if denominator <= 0:
        raise ValueError("分母无效，请检查最大杠杆和费率")
    return available_margin / denominator


def amount(max_open):
    """计算仓位价值，取最大开仓价值的 1%"""
    return round(0.01 * max_open, 2)


def main():
    parser = argparse.ArgumentParser(
        description="从 Gate.io 杠杆限制错误中提取最大杠杆，计算最大可开仓位（USDT价值）并输出1%仓位建议"
    )
    parser.add_argument(
        '-c', '--contract',
        default=DEFAULT_CONTRACT,
        help=f"合约名称，默认 {DEFAULT_CONTRACT}"
    )
    args = parser.parse_args()

    session = requests.Session()
    try:
        print(f"=== 正在获取合约 {args.contract} 的最大杠杆限制 ===")
        max_leverage = get_max_leverage(session, args.contract)
        print(f"合约信息中的最大杠杆: {max_leverage}\n")

        print("正在获取可用保证金...")
        margin = get_total_available_margin(session)
        print(f"可用保证金: {margin:.8f} USDT\n")

        max_open = compute_max_open(margin, max_leverage, FEE_RATE)
        formula = f"{margin:.4f} / (1/{max_leverage} + 2*{FEE_RATE})"

        print(f"{'最大杠杆':>8} | {'最大开仓(USDT)':>20} | 计算公式")
        print("-" * 70)
        print(f"{max_leverage:>8} | {max_open:>20.8f} | {formula}")

        suggested_position = amount(max_open)
        print(f"\n建议仓位价值 (max_open 的 1%): {suggested_position:.2f} USDT\n")

    except Exception as e:
        print(f"执行失败: {e}")
        sys.exit(1)
    finally:
        session.close()
        print("\n[信息] requests 会话已关闭（连接已断开）")


if __name__ == "__main__":
    main()
