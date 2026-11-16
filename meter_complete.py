import argparse
import csv
import os
import socket
import struct
import time

HEADER = struct.Struct('!4sIQd')
MAGIC = b'BWMT'


def save(path, row):
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(row))
        if not exists:
            writer.writeheader()
        writer.writerow(row)
    print(row, flush=True)


def sender(a):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    payload = b'X' * (a.size - HEADER.size)
    count = total = 0
    start = time.time()
    next_send = time.monotonic()
    deadline = next_send + a.duration
    try:
        while time.monotonic() < deadline:
            data = HEADER.pack(MAGIC, a.test_id, count, time.time()) + payload
            try:
                n = sock.sendto(data, (a.dst, a.port))
            except OSError as e:
                print(f'Send error: {e}', flush=True)
                break
            count += 1
            total += n
            if a.rate:
                next_send += 1 / a.rate
                remaining = next_send - time.monotonic()
                if remaining > 0:
                    time.sleep(remaining)
    finally:
        end = time.time()
        sock.close()
    elapsed = max(end - start, 1e-9)
    save(a.out, dict(test_id=a.test_id, start=start, end=end, duration=elapsed, packets=count, bytes=total, mbps=total * 8 / elapsed / 1e6, rate=a.rate, size=a.size))


def receiver(a):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', a.port))
    sock.settimeout(a.idle)
    first = last = None
    seen = set()
    total = duplicates = 0
    latency_sum = 0.0
    try:
        while True:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                break
            now = time.time()
            if len(data) < HEADER.size:
                continue
            magic, test_id, seq, sent_at = HEADER.unpack_from(data)
            if magic != MAGIC or test_id != a.test_id:
                continue
            if seq in seen:
                duplicates += 1
                continue
            seen.add(seq)
            total += len(data)
            latency_sum += (now - sent_at) * 1000
            first = now if first is None else first
            last = now
    finally:
        sock.close()
    elapsed = max((last - first) if first is not None else 0, 1e-9)
    save(a.out, dict(test_id=a.test_id, start=first or 0, end=last or 0, duration=(last - first) if first is not None else 0, packets=len(seen), bytes=total, mbps=total * 8 / elapsed / 1e6 if first is not None else 0, duplicates=duplicates, avg_latency_ms=latency_sum / len(seen) if seen else 0))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['send', 'recv'])
    p.add_argument('--dst', default='10.0.0.2')
    p.add_argument('--port', type=int, default=5005)
    p.add_argument('--rate', type=int, default=500)
    p.add_argument('--size', type=int, default=512)
    p.add_argument('--duration', type=float, default=10)
    p.add_argument('--idle', type=float, default=3)
    p.add_argument('--test-id', type=int, default=1)
    p.add_argument('--out')
    a = p.parse_args()
    if not 1 <= a.port <= 65535 or not HEADER.size <= a.size <= 65507 or a.duration <= 0 or a.rate < 0 or a.idle <= 0:
        p.error('Invalid port, size, duration, rate or idle timeout')
    a.out = a.out or ('send.csv' if a.mode == 'send' else 'recv.csv')
    (sender if a.mode == 'send' else receiver)(a)
