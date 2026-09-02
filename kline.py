# coding: utf-8
import argparse
import json
import os
import re
from urllib.parse import parse_qs, urlencode
from urllib.request import Request, urlopen


host = "https://api.gateio.ws"
prefix = "/api/v4"
url = "/futures/usdt/candlesticks"
headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _timestamp(item):
    """返回 K 线时间戳，用于按时间从旧到新排序。"""
    if not isinstance(item, dict) or "t" not in item:
        raise ValueError("K 线数据缺少时间戳字段 t")
    return int(item["t"])


def db(file_path, query_param):
    """请求并更新本地 K 线文件。已有文件时仅替换最近 8 条数据。"""
    file_exists = os.path.isfile(file_path)
    request_limit = 8 if file_exists else 501

    query = parse_qs(query_param)
    query["limit"] = [str(request_limit)]

    request = Request(
        host + prefix + url + "?" + urlencode(query, doseq=True),
        headers=headers,
    )
    with urlopen(request, timeout=30) as response:
        new_data = json.loads(response.read().decode("utf-8"))

    if not isinstance(new_data, list):
        raise ValueError("接口返回的数据不是列表")

    if file_exists:
        with open(file_path, "r", encoding="utf-8") as f:
            old_data = json.load(f)

        if not isinstance(old_data, list):
            raise ValueError(f"{os.path.basename(file_path)} 中的数据不是列表")

        # 本地数据按时间从旧到新排列，移除最近 8 条，再用接口数据替换。
        old_data = sorted(old_data, key=_timestamp)
        retained_data = old_data[:-8]
        target_count = max(len(old_data), len(new_data))

        # 按时间戳去重；接口返回的新数据优先于本地旧数据。
        merged_by_time = {}
        for item in new_data + retained_data:
            merged_by_time.setdefault(_timestamp(item), item)

        data = sorted(
            merged_by_time.values(),
            key=_timestamp,
        )[-target_count:]
    else:
        # 首次创建文件时正常保存接口返回的 501 条数据。
        data = sorted(new_data, key=_timestamp)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return len(data), request_limit


def normalize_symbol(symbol):
    """规范化并校验币种简称。"""
    symbol = str(symbol).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]+", symbol):
        raise ValueError("币种简称只能包含英文字母和数字，例如 HYPE、SOL 或 BTC")
    return symbol


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="下载或更新 Gate.io USDT 永续合约的 1 小时 K 线数据",
        epilog="示例：python kline.py HYPE（也可传入 SOL、BTC 等币种）",
    )
    parser.add_argument(
        "symbol",
        help="币种简称，例如 HYPE、SOL 或 BTC",
    )
    args = parser.parse_args(argv)

    try:
        symbol = normalize_symbol(args.symbol)
    except ValueError as exc:
        parser.error(str(exc))

    return symbol


def update_kline(symbol, output_dir=None):
    """下载或更新指定币种的 K 线，并返回生成文件的绝对路径。"""
    symbol = normalize_symbol(symbol)
    contract = f"{symbol}_USDT"
    query_param = urlencode(
        {
            "contract": contract,
            "interval": "1h",
            "limit": 501,
        }
    )

    file_name = f"{symbol}_data.js"
    target_dir = (
        os.path.abspath(os.fspath(output_dir))
        if output_dir is not None
        else os.path.dirname(os.path.abspath(__file__))
    )
    os.makedirs(target_dir, exist_ok=True)
    file_path = os.path.join(target_dir, file_name)

    data_count, request_limit = db(file_path, query_param)
    print(f"{file_name} 更新完成：本次请求 {request_limit} 条，当前共 {data_count} 条")
    return file_path


def main(argv=None):
    symbol = parse_args(argv)
    update_kline(symbol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
