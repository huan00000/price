import argparse

import requests


headers = {
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "origin": "https://www.tradingview.com",
    "priority": "u=1, i",
    "referer": "https://www.tradingview.com/",
    "sec-ch-ua": "\"Not=A?Brand\";v=\"99\", \"Google Chrome\";v=\"151\", \"Chromium\";v=\"151\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
}

cookies = {
    "cookiePrivacyPreferenceBannerProduction": "notApplicable",
    "cookiesSettings": "{\"analytics\":true,\"advertising\":true}",
    "device_t": "Y2E1X0NBOjA.XjSKYSMkuiZeYUFrvwTRmC4fgiwPyxIlFzOSwQRaeAc",
    "sessionid": "djy6ac5o5ge4nw9d71m15nf13k7rimtb",
    "sessionid_sign": "v3:EFfA8U/F1gyxQHJUEGji8xc74S/f7lSeQ9MZwape/UQ=",
    "tv_ecuid": "af541b6f-9e2d-46a1-a66f-e434a41f59f7",
    "etg": "af541b6f-9e2d-46a1-a66f-e434a41f59f7",
    "cachec": "af541b6f-9e2d-46a1-a66f-e434a41f59f7",
    "theme": "dark",
    "_sp_ses.cf1a": "*",
    "_sp_id.cf1a": "26756720-bb0e-402b-a7bb-a3bcc3c8dca4.1783390496.40.1787737524.1787731314.470a4cf6-5945-485d-ba4d-d11fd9e4097f.91d15eb8-9783-4e3c-bda9-428767c2b4e3.e49dceae-7fff-480b-bc07-bf537c8b1a56.1787737444506.19"
}

url = "https://scanner.tradingview.com/symbol"

params = {
    "fields": "price_52_week_high,price_52_week_low,sector,country,market,Low.1M,High.1M,Perf.W,Perf.1M,Perf.3M,Perf.6M,Perf.Y,Perf.YTD,Recommend.All,average_volume_10d_calc,average_volume_30d_calc,nav_discount_premium,open_interest,country_code_fund,iv,underlying_symbol,delta,gamma,rho,theta,vega,theoPrice",
    "no_404": "true",
    "label-product": "right-details"
}


def parse_base_asset(value):
    """校验并标准化基础币种，例如 SOL、BTC、1000PEPE。"""
    base_asset = value.strip().upper()
    if not base_asset or not base_asset.isalnum():
        raise argparse.ArgumentTypeError("币种只能包含英文字母和数字，例如 SOL、BTC、1000PEPE")
    return base_asset


def parse_args():
    parser = argparse.ArgumentParser(
        description="查询 GATE USDT 永续合约的 1 个月涨跌幅"
    )
    parser.add_argument(
        "base_asset",
        nargs="?",
        default="BTC",
        type=parse_base_asset,
        help="基础币种，默认值：BTC（例如 BTC、ETH、1000PEPE）"
    )
    return parser.parse_args()


def get_month_performance(base_asset):
    """获取指定币种的 1 个月涨跌幅（百分数，例如 21.21）。"""
    base_asset = parse_base_asset(base_asset)
    request_params = params.copy()
    request_params["symbol"] = f"GATE:{base_asset}USDT.P"

    with requests.Session() as session:
        session.headers.update(headers)
        session.cookies.update(cookies)

        response = session.get(url, params=request_params, timeout=15)
        response.raise_for_status()
        data = response.json()

    perf_1m = data.get("Perf.1M")
    if perf_1m is None:
        raise ValueError("未获取到 Perf.1M 数据")
    return float(perf_1m)


def main(base_asset):
    """命令行入口；打印结果并返回月涨跌幅，便于其他脚本复用。"""
    base_asset = parse_base_asset(base_asset)
    try:
        perf_1m = get_month_performance(base_asset)
        print(f"本次监测到{base_asset}的1个月涨跌幅为：{perf_1m:+.2f}%")

        if perf_1m > 15:
            print("涨幅超过 +15%，建议进行 open short。")
        elif perf_1m < -15:
            print("跌幅超过 -15%，建议进行 open long。")
        else:
            print("涨跌幅位于 -15% ~ +15% 之间，暂不建议操作。")
        return perf_1m
    except requests.RequestException as e:
        print(f"请求失败：{e}")
    except ValueError as e:
        print(f"数据解析失败：{e}")
    return None


if __name__ == "__main__":
    args = parse_args()
    main(args.base_asset)
