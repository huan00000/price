
import argparse
import requests
from contextlib import redirect_stdout
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from io import StringIO

import amount as amount_module


def normalize_contract_name(contract_name):
    """将 BTC、btc_usdt 等输入统一为 Gate.io 使用的 BTC_USDT。"""
    if not isinstance(contract_name, str):
        raise TypeError("交易品种必须是字符串")

    normalized = contract_name.strip().upper()
    if not normalized:
        raise ValueError("交易品种不能为空")
    return normalized if normalized.endswith("_USDT") else f"{normalized}_USDT"

def _get_price_and_action(contract_name):
    """获取挂单价格以及开仓方向，保证两者来自同一次行情分析。"""
    import price as price_module

    base_asset = contract_name.removesuffix("_USDT")
    # 行情模块会打印更新日志；本脚本按要求只保留最终下单结果。
    with redirect_stdout(StringIO()):
        perf_1m = price_module.get_month_performance(base_asset)
        structure = price_module.get_structure(base_asset, 50)
        final_price = price_module.price(perf_1m, structure)

    if final_price is None:
        return None, None

    action = (
        "Open Short"
        if str(structure["weak_type"]).lower() == "high"
        else "Open Long"
    )
    return final_price, action


def getprice(contract_name=None):
    """获取当前交易品种的 FINAL_PRICE。

    ``price.analyze()`` 在没有潜在交易机会时会返回 ``None``。
    """
    contract_name = normalize_contract_name(contract_name) if contract_name else contract()
    final_price, _ = _get_price_and_action(contract_name)
    return final_price

def contract():
    """请求用户输入币种简称，并返回 Gate.io 的 USDT 合约名称。"""
    default_symbol = amount_module.DEFAULT_CONTRACT.removesuffix("_USDT")
    value = input(
        f"请输入交易品种（默认 {default_symbol}，如 CL/BTC/ETH）: "
    ).strip().upper()
    return normalize_contract_name(value or default_symbol)


def get_max_leverage(session, contract_name):
    """通过公开合约信息接口取得合约最大杠杆。"""
    return amount_module.get_max_leverage(session, contract_name)


def amount(contract_name=None):
    """计算指定交易品种的建议仓位价值（最大开仓价值的 1%）。"""
    contract_name = normalize_contract_name(contract_name) if contract_name else contract()

    with requests.Session() as session:
        max_leverage = get_max_leverage(session, contract_name)
        available_margin = amount_module.get_total_available_margin(session)

    max_open = amount_module.compute_max_open(
        available_margin,
        max_leverage,
        amount_module.FEE_RATE,
    )
    suggested_position = amount_module.amount(max_open)

    return suggested_position

def getquanto_multiplier(contract_name=None, session=None):
    """获取指定 USDT 合约的 quanto_multiplier，返回原始字符串值。"""
    contract_name = normalize_contract_name(contract_name or contract())
    url = f"/futures/usdt/contracts/{contract_name}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    owns_session = session is None
    session = session or requests.Session()
    try:
        response = session.get(
            amount_module.HOST + amount_module.PREFIX + url,
            headers=headers,
            timeout=15,
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"获取 {contract_name} quanto_multiplier 失败: "
                f"HTTP {response.status_code} {response.text}"
            ) from exc

        if not response.ok:
            raise RuntimeError(
                f"获取 {contract_name} quanto_multiplier 失败: "
                f"HTTP {response.status_code} {data}"
            )

        quanto_multiplier = data.get("quanto_multiplier")
        if quanto_multiplier is None:
            raise RuntimeError(
                f"{contract_name} 的合约信息缺少 quanto_multiplier: {data}"
            )
        return str(quanto_multiplier)
    finally:
        if owns_session:
            session.close()

def size(contract_name=None):
    """计算下单张数；做空返回负整数，做多返回正整数。

    没有潜在交易机会（即未取得 FINAL_PRICE）时返回 ``None``。张数向零
    取整，确保实际仓位价值不会超过建议仓位价值。
    """
    contract_name = normalize_contract_name(contract_name) if contract_name else contract()
    final_price, action = _get_price_and_action(contract_name)
    if final_price is None:
        return None

    suggested_amount = amount(contract_name)
    quanto_multiplier = getquanto_multiplier(contract_name)

    try:
        amount_value = Decimal(str(suggested_amount))
        multiplier_value = Decimal(str(quanto_multiplier))
        price_value = Decimal(str(final_price))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount、quanto_multiplier 和 price 必须是有效数字") from exc

    if not all(
        value.is_finite()
        for value in (amount_value, multiplier_value, price_value)
    ):
        raise ValueError("amount、quanto_multiplier 和 price 必须是有限数字")
    if amount_value < 0:
        raise ValueError("建议仓位价值不能为负数")
    if multiplier_value <= 0 or price_value <= 0:
        raise ValueError("quanto_multiplier 和 price 必须大于 0")

    unsigned_size = int(amount_value / (multiplier_value * price_value))
    if unsigned_size == 0:
        return None

    order_size = -unsigned_size if action == "Open Short" else unsigned_size

    display_price = price_value.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    direction_icon = "📉" if action == "Open Short" else "📈"
    order_details = (
        ("✨", "Symbol", contract_name),
        ("💰", "Price", f"{display_price:.4f} USDT"),
        (direction_icon, "Direction", action),
        ("📦", "Size", f"{order_size} 张"),
    )
    label_width = max(len(label) for _, label, _ in order_details)

    print("\n🚀 ====== Order Alert ======")
    for icon, label, value in order_details:
        print(f"{icon}  {label:<{label_width}} : {value}")
    print("   ======================\n")
    return order_size

def main(argv=None):
    parser = argparse.ArgumentParser(description="计算合约下单张数")
    parser.add_argument(
        "contracts",
        nargs="*",
        help="交易品种，例如 BTC ETH；不传参数时使用交互输入",
    )
    args = parser.parse_args(argv)

    contracts = args.contracts or [None]
    failed = False
    for contract_name in contracts:
        try:
            order_size = size(contract_name)
            if order_size is None:
                print("none")
        except (requests.RequestException, RuntimeError, TypeError, ValueError) as exc:
            failed = True
            print(f"执行失败: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
