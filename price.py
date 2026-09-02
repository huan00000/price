"""
结合月涨跌幅与 SMC 结构计算潜在挂单价格。

示例：
    python price.py BTC
    python price.py BTC ETH HYPE SOL
    python price.py HYPE
    python price.py SPX500
    python price.py ETH

输出内容格式:
===== HYPE =====
HYPE_data.js 更新完成：本次请求 8 条，当前共 501 条
本次监测到HYPE的1个月涨跌幅为：+52.34%
当前r值为+12.51%
weak high，weak price = 87.58
open short FINAL_PRICE = 88.46
"""

import argparse
import re

from month import get_month_performance, parse_base_asset
from smc import get_structure


def price(perf_1m, structure):
    """按月涨跌幅、r 值和 weak 类型计算 FINAL_PRICE。

    ``perf_1m`` 和 ``structure['ratio']`` 分别使用百分数（如 21.21）和
    小数（如 0.12）。最终价格以 SMC 输出中的 ``weak price``，即
    ``adjusted_weak_price`` 为基准。
    """
    perf_1m = float(perf_1m)
    ratio = float(structure["ratio"])
    weak_type = str(structure["weak_type"]).lower()
    weak_price = float(structure["adjusted_weak_price"])

    if perf_1m > 15 and ratio > 0.10 and weak_type == "high":
        return 1.01 * weak_price
    if perf_1m < -15 and ratio < -0.10 and weak_type == "low":
        return 0.99 * weak_price
    return None


def analyze(base_asset, swing_length=50):
    """用同一个币种参数获取 month 与 SMC 结果并执行判断。"""
    base_asset = parse_base_asset(base_asset)
    perf_1m = get_month_performance(base_asset)
    structure = get_structure(base_asset, swing_length)
    final_price = price(perf_1m, structure)

    print(f"本次监测到{base_asset}的1个月涨跌幅为：{perf_1m:+.2f}%")
    print(f"当前r值为{structure['ratio'] * 100:+.2f}%")
    print(
        f"weak {structure['weak_type']}，"
        f"weak price = {structure['adjusted_weak_price']:.2f}"
    )
    if final_price is None:
        print("暂无潜在交易机会")
    else:
        action = "open short" if str(structure["weak_type"]).lower() == "high" else "open long"
        print(f"{action} FINAL_PRICE = {final_price:.2f}")

    return final_price


def parse_assets(values):
    """同时支持空格、英文句点和中英文逗号分隔多个币种。"""
    assets = []
    for value in values:
        assets.extend(item for item in re.split(r"[.,，、]+", value) if item)
    return [parse_base_asset(asset) for asset in assets]


def main(argv=None):
    parser = argparse.ArgumentParser(description="结合 month 与 SMC 计算 FINAL_PRICE")
    parser.add_argument(
        "base_assets",
        nargs="+",
        help="币种，例如 BTC，或 BTC ETH HYPE SOL",
    )
    parser.add_argument(
        "-s", "--swing-length", type=int, default=50,
        help="SMC 摆动高低点周期，默认 50",
    )
    args = parser.parse_args(argv)
    if args.swing_length < 1:
        parser.error("--swing-length 必须大于 0")

    assets = parse_assets(args.base_assets)
    failed = False
    for index, asset in enumerate(assets):
        if index:
            print()
        print(f"===== {asset} =====")
        try:
            analyze(asset, args.swing_length)
        except Exception as exc:
            failed = True
            print(f"处理失败：{exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
