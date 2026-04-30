import argparse
import calendar
import csv
import lzma
import os
import struct
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests


def dukascopy_url(symbol: str, dt: datetime) -> str:
    return (
        f"https://datafeed.dukascopy.com/datafeed/{symbol}/"
        f"{dt.year}/{dt.month - 1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
    )


def download_hour(symbol: str, dt: datetime, timeout: int = 30):
    url = dukascopy_url(symbol, dt)
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code != 200 or len(response.content) < 20:
            return None, f"SKIP {dt:%Y-%m-%d %H:%M} status={response.status_code} size={len(response.content)}"
        return response.content, f"OK {dt:%Y-%m-%d %H:%M} size={len(response.content)}"
    except Exception as exc:
        return None, f"ERROR {dt:%Y-%m-%d %H:%M} {exc}"


def parse_bi5_ticks(content: bytes, hour_dt: datetime, price_scale: float):
    try:
        raw = lzma.decompress(content)
    except Exception as exc:
        return [], f"DECOMPRESS_FAILED {hour_dt:%Y-%m-%d %H:%M} {exc}"

    rows = []
    record_size = 20

    for i in range(0, len(raw), record_size):
        chunk = raw[i:i + record_size]
        if len(chunk) != record_size:
            continue

        time_ms, ask_i, bid_i, ask_vol, bid_vol = struct.unpack(">IIIff", chunk)
        utc_time = hour_dt + timedelta(milliseconds=time_ms)
        ist_time = utc_time.astimezone(ZoneInfo("Asia/Kolkata"))

        bid = bid_i / price_scale
        ask = ask_i / price_scale

        rows.append([
            utc_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            ist_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            f"{bid:.3f}",
            f"{ask:.3f}",
            f"{bid_vol:.6f}",
            f"{ask_vol:.6f}",
        ])

    return rows, None


def download_month(symbol: str, year: int, month: int, output_dir: str, price_scale: float):
    os.makedirs(output_dir, exist_ok=True)

    month_label = f"{year}_{month:02d}"
    csv_name = f"{symbol}_TICK_{month_label}_DUKASCOPY_BID_ASK_UTC_IST.csv"
    log_name = f"{symbol}_TICK_{month_label}_download_log.txt"
    zip_name = f"{symbol}_TICK_{month_label}_DUKASCOPY.zip"

    csv_path = os.path.join(output_dir, csv_name)
    log_path = os.path.join(output_dir, log_name)
    zip_path = os.path.join(output_dir, zip_name)

    last_day = calendar.monthrange(year, month)[1]
    start_dt = datetime(year, month, 1, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(year, month, last_day, 23, 0, tzinfo=timezone.utc)

    total_ticks = 0
    downloaded_hours = 0
    skipped_hours = 0
    error_hours = 0
    log_lines = []

    print(f"START {symbol} {month_label}")
    print(f"UTC range: {start_dt} to {end_dt}")

    with open(csv_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["utc_time", "ist_time", "bid", "ask", "bid_volume", "ask_volume"])

        current = start_dt
        while current <= end_dt:
            content, message = download_hour(symbol, current)
            log_lines.append(message)

            if content is None:
                skipped_hours += 1
                if message.startswith("ERROR"):
                    error_hours += 1
            else:
                rows, parse_error = parse_bi5_ticks(content, current, price_scale)
                if parse_error:
                    log_lines.append(parse_error)
                    error_hours += 1
                    skipped_hours += 1
                elif rows:
                    writer.writerows(rows)
                    total_ticks += len(rows)
                    downloaded_hours += 1
                else:
                    skipped_hours += 1

            current += timedelta(hours=1)

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write("\n".join(log_lines))
        log_file.write("\n\n")
        log_file.write(f"symbol={symbol}\n")
        log_file.write(f"month={month_label}\n")
        log_file.write(f"total_ticks={total_ticks}\n")
        log_file.write(f"downloaded_hours={downloaded_hours}\n")
        log_file.write(f"skipped_hours={skipped_hours}\n")
        log_file.write(f"error_hours={error_hours}\n")
        log_file.write(f"csv_file={csv_name}\n")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:
        zip_file.write(csv_path, arcname=csv_name)
        zip_file.write(log_path, arcname=log_name)

    print("DONE")
    print(f"symbol={symbol}")
    print(f"month={month_label}")
    print(f"total_ticks={total_ticks}")
    print(f"downloaded_hours={downloaded_hours}")
    print(f"skipped_hours={skipped_hours}")
    print(f"error_hours={error_hours}")
    print(f"zip_path={zip_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--price-scale", type=float, default=1000.0)
    args = parser.parse_args()

    download_month(
        symbol=args.symbol,
        year=args.year,
        month=args.month,
        output_dir=args.output_dir,
        price_scale=args.price_scale,
    )


if __name__ == "__main__":
    main()
