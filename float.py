"""读取 Gate.io 永续合约价格，并计算各价格的小数精度。

默认读取同目录 ``symbol.txt``，也可以直接传入币种：
``python float.py BTC ETH DOGE``。
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests


HOST = "https://api.gateio.ws"
PREFIX = "/api/v4"
HEADERS = {"Accept": "application/json"}
PRICE_FIELDS = ("last_price", "mark_price", "index_price")
DEFAULT_SYMBOL_FILE = Path(__file__).with_name("symbol.txt")
DEFAULT_OUTPUT_FILE = Path(__file__).with_name("float.js")


def normalize_contract(symbol: str) -> str:
    """把 ``BTC``、``btc_usdt`` 等输入统一成 ``BTC_USDT``。"""
    value = symbol.strip().upper().replace("-", "_")
    if not value:
        raise ValueError("币种不能为空")
    if "_" not in value:
        value = f"{value}_USDT"
    if not value.endswith("_USDT"):
        raise ValueError(f"仅支持 USDT 永续合约: {symbol!r}")
    return value


def decimal_step(value: Any) -> Decimal:
    """根据价格文本的小数位返回步长，并保留尾随零表达的精度。"""
    if value is None or isinstance(value, bool):
        raise ValueError("价格不能为空")
    text = str(value).strip()
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"无效价格: {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"价格必须是有限数值: {value!r}")
    exponent = number.as_tuple().exponent
    return Decimal(1).scaleb(exponent) if exponent < 0 else Decimal(1)


def get_price_precision(
    contract: str,
    session: requests.Session | None = None,
    timeout: float = 15,
) -> dict[str, dict[str, Decimal]]:
    """获取合约的三个价格，并返回各自的数值及小数步长。"""
    contract = normalize_contract(contract)
    client = session or requests.Session()
    owns_session = session is None
    url = f"{HOST}{PREFIX}/futures/usdt/contracts/{contract}"
    try:
        response = client.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{contract} 返回的不是有效 JSON") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"获取 {contract} 价格失败: {exc}") from exc
    finally:
        if owns_session:
            client.close()

    result: dict[str, dict[str, Decimal]] = {}
    for field in PRICE_FIELDS:
        raw = data.get(field)
        if raw in (None, ""):
            raise RuntimeError(f"{contract} 返回数据缺少 {field}")
        try:
            result[field] = {"value": Decimal(str(raw)), "step": decimal_step(raw)}
        except (InvalidOperation, ValueError) as exc:
            raise RuntimeError(f"{contract} 的 {field} 无效: {raw!r}") from exc
    return result


def read_symbols(path: Path = DEFAULT_SYMBOL_FILE) -> list[str]:
    """读取币种文件；忽略空行和注释，去重并保持原顺序。"""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise RuntimeError(f"无法读取币种文件 {path}: {exc}") from exc

    symbols: list[str] = []
    seen: set[str] = set()
    for line in lines:
        value = line.split("#", 1)[0].strip()
        if value:
            contract = normalize_contract(value)
            if contract not in seen:
                symbols.append(contract)
                seen.add(contract)
    if not symbols:
        raise RuntimeError(f"币种文件为空: {path}")
    return symbols


def format_decimal(value: Decimal) -> str:
    """不用科学计数法输出 Decimal。"""
    return format(value, "f")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="读取 Gate.io 合约价格及小数精度")
    parser.add_argument("symbols", nargs="*", help="币种，例如 BTC ETH 或 BTC_USDT")
    parser.add_argument("--file", type=Path, default=DEFAULT_SYMBOL_FILE, help="币种文件")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT_FILE, help="结果输出文件"
    )
    parser.add_argument("--timeout", type=float, default=15, help="请求超时秒数")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")

    try:
        contracts = (
            list(dict.fromkeys(normalize_contract(item) for item in args.symbols))
            if args.symbols
            else read_symbols(args.file)
        )
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))

    failed = False
    output_data: list[dict[str, Any]] = []
    with requests.Session() as session:
        for contract in contracts:
            try:
                prices = get_price_precision(contract, session, args.timeout)
                max_step = max(prices[field]["step"] for field in PRICE_FIELDS)
                output_data.append(
                    {"contract": contract, "step": format_decimal(max_step)}
                )
            except (RuntimeError, ValueError) as exc:
                failed = True
                print(f"跳过 {contract}: {exc}", file=sys.stderr)

    try:
        args.output.write_text(
            json.dumps(output_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        parser.error(f"无法写入结果文件 {args.output}: {exc}")

    print(f"结果已写入: {args.output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
