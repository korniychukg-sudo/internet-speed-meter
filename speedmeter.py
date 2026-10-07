#!/usr/bin/env python3
import argparse
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional

DEFAULT_URL = "https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg"
CHUNK_SIZE = 64 * 1024
USER_AGENT = "internet-speed-meter/1.0 (+https://github.com/korniychukg-sudo/internet-speed-meter)"


@dataclass
class Attempt:
    number: int
    seconds: float
    bytes_received: int
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class Summary:
    url: str
    attempts: List[Attempt]

    @property
    def successful(self) -> List[Attempt]:
        return [a for a in self.attempts if a.ok]

    @property
    def total_bytes(self) -> int:
        return sum(a.bytes_received for a in self.successful)

    @property
    def total_seconds(self) -> float:
        return sum(a.seconds for a in self.successful)

    @property
    def average_seconds(self) -> float:
        ok = self.successful
        return statistics.mean(a.seconds for a in ok) if ok else 0.0

    @property
    def megabytes_per_second(self) -> float:
        return self.total_bytes / self.total_seconds / 1_000_000 if self.total_seconds else 0.0

    @property
    def megabits_per_second(self) -> float:
        return self.megabytes_per_second * 8


def fetch_once(url: str, timeout: float) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    received = 0
    with urllib.request.urlopen(request, timeout=timeout) as response:
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            received += len(chunk)
    return received


def measure(url: str, count: int = 10, timeout: float = 30.0,
            fetch: Callable[[str, float], int] = fetch_once,
            clock: Callable[[], float] = time.perf_counter,
            on_attempt: Optional[Callable[[Attempt], None]] = None) -> Summary:
    attempts: List[Attempt] = []
    for number in range(1, count + 1):
        started = clock()
        try:
            received = fetch(url, timeout)
            attempt = Attempt(number, clock() - started, received)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            attempt = Attempt(number, clock() - started, 0, error=describe_error(exc))
        attempts.append(attempt)
        if on_attempt:
            on_attempt(attempt)
    return Summary(url, attempts)


def describe_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"сетевая ошибка: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def format_megabytes(num_bytes: int) -> str:
    return f"{num_bytes / 1_000_000:.2f} МБ"


def print_attempt(attempt: Attempt) -> None:
    if attempt.ok:
        speed = attempt.bytes_received / attempt.seconds / 1_000_000 if attempt.seconds else 0.0
        print(f"  запрос {attempt.number:>2}: {attempt.seconds:6.2f} с, {format_megabytes(attempt.bytes_received):>9}, {speed:6.2f} МБ/с")
    else:
        print(f"  запрос {attempt.number:>2}: ошибка ({attempt.error}) через {attempt.seconds:.2f} с")


def print_summary(summary: Summary) -> None:
    ok = len(summary.successful)
    total = len(summary.attempts)
    print()
    print(f"Успешных запросов: {ok} из {total}")
    if not ok:
        print("Скорость посчитать не удалось: ни один запрос не завершился успешно.")
        return
    print(f"Среднее время запроса: {summary.average_seconds:.2f} с")
    print(f"Скачано всего: {format_megabytes(summary.total_bytes)}")
    print(f"Скорость: {summary.megabytes_per_second:.2f} МБ/с ({summary.megabits_per_second:.1f} Мбит/с)")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Замер скорости интернета: N последовательных скачиваний файла по адресу.")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL,
                        help="адрес тяжёлого файла, например большой картинки (по умолчанию фото ~15 МБ с Wikimedia)")
    parser.add_argument("-n", "--count", type=int, default=10, help="число запросов (по умолчанию 10)")
    parser.add_argument("-t", "--timeout", type=float, default=30.0, help="таймаут одного запроса в секундах (по умолчанию 30)")
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("число запросов должно быть не меньше 1")
    if args.timeout <= 0:
        parser.error("таймаут должен быть больше 0")
    if not args.url.startswith(("http://", "https://")):
        parser.error("адрес должен начинаться с http:// или https://")
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    print(f"Адрес: {args.url}")
    print(f"Запросов: {args.count}, таймаут: {args.timeout:g} с")
    try:
        summary = measure(args.url, args.count, args.timeout, on_attempt=print_attempt)
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
        return 130
    print_summary(summary)
    return 0 if summary.successful else 1


if __name__ == "__main__":
    sys.exit(main())
