"""Faithful Python port of LuxAlgo SMC Strong/Weak High/Low state.

Only the Pine logic involved in ``Show Strong/Weak High/Low`` is ported.
The calculation is deliberately bar-by-bar because Pine variables are stateful.
python smc.py SPX500
python smc.py ETH
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np


BULLISH_LEG = 1
BEARISH_LEG = 0
BULLISH = 1
BEARISH = -1


@dataclass
class StructureResult:
    top_type: str
    top_price: float
    bottom_type: str
    bottom_price: float
    trend: str
    trend_bias: int
    top_index: object
    bottom_index: object
    swing_high: Optional[float]
    swing_low: Optional[float]
    swing_high_index: object
    swing_low_index: object


def load_ohlcv(source: str | Path) -> pd.DataFrame:
    """Read CSV, JSON, or ``const data = [...]`` style JS OHLC data."""
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(f"找不到输入文件: {path}")

    if path.suffix.lower() == ".csv":
        data = pd.read_csv(path)
    else:
        text = path.read_text(encoding="utf-8-sig").strip()
        if "=" in text and not text.lstrip().startswith(("[", "{")):
            text = text.split("=", 1)[1].strip().rstrip(";")
        try:
            records = json.loads(text)
        except json.JSONDecodeError:
            records = ast.literal_eval(text)
        if isinstance(records, dict):
            records = records.get("data", records.get("rows", records))
        if not isinstance(records, list):
            raise ValueError("输入必须是 K 线数组，或包含 data/rows 数组的对象")
        data = pd.DataFrame(records)

    aliases = {
        "o": "open", "h": "high", "l": "low", "c": "close",
        "v": "volume", "t": "timestamp",
    }
    data = data.rename(
        columns={str(c).lower(): aliases.get(str(c).lower(), str(c).lower()) for c in data.columns}
    )
    required = ["open", "high", "low", "close"]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ValueError("缺少必要字段: " + ", ".join(missing))
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="raise")

    if "timestamp" in data.columns:
        numeric_time = pd.to_numeric(data["timestamp"], errors="coerce")
        unit = "ms" if numeric_time.dropna().abs().median() > 10_000_000_000 else "s"
        data.index = pd.to_datetime(numeric_time, unit=unit, utc=True)
        data.index.name = "timestamp"

    if not data.index.is_monotonic_increasing:
        data = data.sort_index()
    return data


def resolve_source(value: str) -> Path:
    """Resolve a file directly, or use the neighbouring kline.py for a symbol."""
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return candidate
    if candidate.suffix or candidate.parent != Path("."):
        raise FileNotFoundError(f"找不到输入文件: {candidate}")

    import kline

    return Path(kline.update_kline(value))


def pine_weak_strong(ohlc: pd.DataFrame, swing_length: int = 50) -> StructureResult:
    """Port the Strong/Weak High/Low state from ``smc.pine``.

    Pine equivalence covered here:
    ``leg(size)`` -> ``getCurrentStructure(size, false)`` ->
    ``displayStructure()`` -> ``drawHighLowSwings()``.
    """
    if swing_length < 1:
        raise ValueError("swing_length 必须大于 0")
    if len(ohlc) <= swing_length:
        raise ValueError(
            f"K线数量不足：至少需要 {swing_length + 1} 根，当前 {len(ohlc)} 根"
        )

    highs = ohlc["high"].to_numpy(dtype=float)
    lows = ohlc["low"].to_numpy(dtype=float)
    closes = ohlc["close"].to_numpy(dtype=float)

    # Pine ``var`` state. leg() starts at BEARISH_LEG; swingTrend starts at 0.
    leg_state = BEARISH_LEG
    trend_bias = 0
    swing_high = None
    swing_low = None
    swing_high_crossed = False
    swing_low_crossed = False
    swing_high_position = None
    swing_low_position = None
    trailing_top = None
    trailing_bottom = None
    trailing_top_position = None
    trailing_bottom_position = None

    for i in range(len(ohlc)):
        # Pine executes updateTrailingExtremes() before pivot detection each bar.
        if trailing_top is not None and highs[i] >= trailing_top:
            trailing_top = highs[i]
            trailing_top_position = i
        if trailing_bottom is not None and lows[i] <= trailing_bottom:
            trailing_bottom = lows[i]
            trailing_bottom_position = i

        previous_leg = leg_state
        previous_swing_high = swing_high
        previous_swing_low = swing_low

        if i >= swing_length:
            candidate = i - swing_length
            # ta.highest(size)/ta.lowest(size) cover the current bar and the
            # preceding size-1 bars, i.e. exactly the bars right of candidate.
            right_highest = highs[i - swing_length + 1 : i + 1].max()
            right_lowest = lows[i - swing_length + 1 : i + 1].min()
            new_leg_high = highs[candidate] > right_highest
            new_leg_low = lows[candidate] < right_lowest

            # Pine uses if/else-if, so a qualifying high has precedence.
            if new_leg_high:
                leg_state = BEARISH_LEG
            elif new_leg_low:
                leg_state = BULLISH_LEG

            if leg_state != previous_leg:
                if leg_state == BULLISH_LEG:
                    swing_low = lows[candidate]
                    swing_low_position = candidate
                    swing_low_crossed = False
                    trailing_bottom = swing_low
                    trailing_bottom_position = candidate
                else:
                    swing_high = highs[candidate]
                    swing_high_position = candidate
                    swing_high_crossed = False
                    trailing_top = swing_high
                    trailing_top_position = candidate

        # ta.crossover(a,b): a > b and a[1] <= b[1]. The b series can change
        # on this bar when a newly confirmed pivot is assigned.
        if (
            i > 0
            and swing_high is not None
            and previous_swing_high is not None
            and closes[i] > swing_high
            and closes[i - 1] <= previous_swing_high
            and not swing_high_crossed
        ):
            swing_high_crossed = True
            trend_bias = BULLISH

        # Pine evaluates the bearish branch after the bullish branch.
        if (
            i > 0
            and swing_low is not None
            and previous_swing_low is not None
            and closes[i] < swing_low
            and closes[i - 1] >= previous_swing_low
            and not swing_low_crossed
        ):
            swing_low_crossed = True
            trend_bias = BEARISH

    if trailing_top is None or trailing_bottom is None:
        raise ValueError("数据中尚未确认完整的 Swing High 和 Swing Low")

    top_type = "Strong High" if trend_bias == BEARISH else "Weak High"
    bottom_type = "Strong Low" if trend_bias == BULLISH else "Weak Low"
    trend = "BULLISH" if trend_bias == BULLISH else "BEARISH" if trend_bias == BEARISH else "UNSET"

    def index_at(position):
        return None if position is None else ohlc.index[position]

    return StructureResult(
        top_type=top_type,
        top_price=float(trailing_top),
        bottom_type=bottom_type,
        bottom_price=float(trailing_bottom),
        trend=trend,
        trend_bias=trend_bias,
        top_index=index_at(trailing_top_position),
        bottom_index=index_at(trailing_bottom_position),
        swing_high=None if swing_high is None else float(swing_high),
        swing_low=None if swing_low is None else float(swing_low),
        swing_high_index=index_at(swing_high_position),
        swing_low_index=index_at(swing_low_position),
    )


def serializable(result: StructureResult) -> dict:
    record = asdict(result)
    for key in ("top_index", "bottom_index", "swing_high_index", "swing_low_index"):
        if record[key] is not None:
            record[key] = str(record[key])
    return record


def ratio(weak, strong, o):
    """计算 weak 相对 strong 的有向比例：(weak - strong) / o。"""
    weak = float(weak)
    strong = float(strong)
    o = float(o)
    if o == 0:
        raise ValueError("开盘价 o 不能为 0")
    return (weak - strong) / o


def classify_ratio(value):
    """按 r 值判断当前是否存在潜在交易机会。"""
    value = float(value)
    if value > 0.10:
        return "涨势过猛，有潜在开空交易机会。"
    if value < -0.10:
        return "跌势太猛，有潜在开多交易机会。"
    return "波动较小，没有潜在交易机会。"


def atr14(ohlc):
    """计算 Wilder ATR(14)，返回与 ``ohlc`` 同索引的 Series。"""
    period = 14
    if len(ohlc) < period:
        raise ValueError(f"K线数量不足：计算 ATR14 至少需要 {period} 根")

    previous_close = ohlc["close"].shift(1)
    true_range = pd.concat(
        [
            ohlc["high"] - ohlc["low"],
            (ohlc["high"] - previous_close).abs(),
            (ohlc["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    values = np.full(len(true_range), np.nan, dtype=float)
    values[period - 1] = float(true_range.iloc[:period].mean())
    for position in range(period, len(true_range)):
        values[position] = (
            values[position - 1] * (period - 1) + float(true_range.iloc[position])
        ) / period
    return pd.Series(values, index=ohlc.index, name="ATR14")


def weak_strong_structure(ohlc, result: StructureResult):
    """把 LuxAlgo 结构结果转换为 smc1 格式化函数需要的字段。"""
    if result.top_type == "Weak High":
        weak_type = "high"
        weak_price = result.top_price
        strong_price = result.bottom_price
    else:
        weak_type = "low"
        weak_price = result.bottom_price
        strong_price = result.top_price

    current_atr14 = float(atr14(ohlc).iloc[-1])
    adjusted_weak_price = (
        weak_price - current_atr14
        if weak_type == "low"
        else weak_price + current_atr14
    )
    current_ratio = ratio(weak_price, strong_price, ohlc["open"].iloc[-1])
    return {
        "weak_type": weak_type,
        "weak_price": weak_price,
        "adjusted_weak_price": adjusted_weak_price,
        "ratio": current_ratio,
        "ratio_classification": classify_ratio(current_ratio),
    }


def format_weak_strong(structure, decimals=2):
    """把结构格式化为适合交易监控终端阅读的多行文本。"""
    return (
        f"当前r值为{structure['ratio']*100:.2f}%.\n\n"
        f"{structure['ratio_classification']}\n\n"
        f"weak {structure['weak_type']}-"
        f"{structure['weak_price']:.{decimals}f}\n\n"
        f"weak price = "
        f"{structure['adjusted_weak_price']:.{decimals}f}"
    )


def get_structure(value, swing_length=50):
    """更新/读取 K 线并返回 weak/strong 结构，供其他脚本调用。"""
    source = resolve_source(value)
    ohlc = load_ohlcv(source)
    result = pine_weak_strong(ohlc, swing_length)
    return weak_strong_structure(ohlc, result)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="按 LuxAlgo smc.pine 逻辑计算 Strong/Weak High/Low"
    )
    parser.add_argument("input", help="币种简称（如 BTC）或 CSV/JSON/JS K线文件")
    parser.add_argument("-s", "--swing-length", type=int, default=50)
    parser.add_argument("-o", "--output", help="可选的 JSON 输出文件")
    parser.add_argument("--decimals", type=int, default=2)
    args = parser.parse_args(argv)

    try:
        source = resolve_source(args.input)
        ohlc = load_ohlcv(source)
        result = pine_weak_strong(ohlc, args.swing_length)
        structure = weak_strong_structure(ohlc, result)
        print(format_weak_strong(structure, args.decimals))
        if args.output:
            output = Path(args.output).expanduser()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(serializable(result), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return 0
    except Exception as exc:
        parser.exit(1, f"计算失败: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
