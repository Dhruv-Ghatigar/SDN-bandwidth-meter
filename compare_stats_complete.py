import argparse
import csv
import os


def read(path):
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def sample_delta(rows, dpid, port, start, end, fields):
    selected = sorted((r for r in rows if int(r['dpid']) == dpid and int(r['port_no']) == port), key=lambda r: float(r['timestamp']))
    before = [r for r in selected if float(r['timestamp']) <= start]
    after = [r for r in selected if float(r['timestamp']) >= end]
    if not before or not after:
        raise ValueError('Missing SDN samples before and after the sender interval')
    return {k: int(after[0][k]) - int(before[-1][k]) for k in fields}


def flow_delta(rows, dpid, port, start, end):
    selected = sorted((r for r in rows if int(r['dpid']) == dpid and str(r['in_port']) == str(port)), key=lambda r: float(r['timestamp']))
    before = [r for r in selected if float(r['timestamp']) <= start]
    after = [r for r in selected if float(r['timestamp']) >= end]
    if not before or not after:
        return None
    first = {}
    last = {}
    for r in before:
        first[(r['in_port'], r['out_port'], r['eth_dst'])] = r
    for r in after:
        last[(r['in_port'], r['out_port'], r['eth_dst'])] = r
    common = first.keys() & last.keys()
    return {k: sum(max(0, int(last[key][k]) - int(first[key][k])) for key in common) for k in ('packet_count', 'byte_count')} if common else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--send', default='send.csv')
    p.add_argument('--recv', default='recv.csv')
    p.add_argument('--sdn', default='sdn_port_stats.csv')
    p.add_argument('--flows', default='sdn_flow_stats.csv')
    p.add_argument('--dpid', type=int, default=1)
    p.add_argument('--in-port', type=int, default=1)
    p.add_argument('--out-port', type=int, default=2)
    p.add_argument('--out', default='comparison.csv')
    a = p.parse_args()
    sends, recvs = read(a.send), read(a.recv)
    ports = read(a.sdn)
    flows = read(a.flows) if os.path.exists(a.flows) else []
    results = []
    for s in sends:
        candidates = [r for r in recvs if r['test_id'] == s['test_id']]
        if not candidates:
            print(f"Skipping test {s['test_id']}: no receiver result")
            continue
        r = candidates[-1]
        start, end = float(s['start']), float(s['end'])
        duration = end - start
        if duration <= 0:
            continue
        fields = ['rx_packets', 'tx_packets', 'rx_bytes', 'tx_bytes', 'rx_dropped', 'tx_dropped']
        incoming = sample_delta(ports, a.dpid, a.in_port, start, end, fields)
        outgoing = sample_delta(ports, a.dpid, a.out_port, start, end, fields)
        flow = flow_delta(flows, a.dpid, a.in_port, start, end)
        sent, received = int(s['packets']), int(r['packets'])
        lost = max(0, sent - received)
        result = dict(test_id=s['test_id'], rate=s['rate'], size=s['size'], duration=duration, sent_packets=sent, received_packets=received, lost_packets=lost, loss_percent=100 * lost / sent if sent else 0, app_send_mbps=float(s['mbps']), app_receive_mbps=int(r['bytes']) * 8 / duration / 1e6, switch_in_packets=incoming['rx_packets'], switch_out_packets=outgoing['tx_packets'], switch_in_mbps=incoming['rx_bytes'] * 8 / duration / 1e6, switch_out_mbps=outgoing['tx_bytes'] * 8 / duration / 1e6, switch_loss_packets=max(0, incoming['rx_packets'] - outgoing['tx_packets']), switch_rx_dropped=incoming['rx_dropped'], switch_tx_dropped=outgoing['tx_dropped'], flow_packets=flow['packet_count'] if flow else '', flow_mbps=flow['byte_count'] * 8 / duration / 1e6 if flow else '', avg_latency_ms=r['avg_latency_ms'])
        results.append(result)
    if not results:
        raise SystemExit('No matching tests available')
    with open(a.out, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    print(f"{'Test':>6} {'Rate':>8} {'Sent':>9} {'Received':>9} {'Loss %':>9} {'App Mbps':>10} {'SDN Mbps':>10} {'Flow Mbps':>10}")
    for r in results:
        flow_mbps = f"{r['flow_mbps']:.3f}" if r['flow_mbps'] != '' else 'N/A'
        print(f"{r['test_id']:>6} {int(r['rate']):>8} {r['sent_packets']:>9} {r['received_packets']:>9} {r['loss_percent']:>9.2f} {r['app_receive_mbps']:>10.3f} {r['switch_out_mbps']:>10.3f} {flow_mbps:>10}")
    print(f'Results saved to {a.out}')


if __name__ == '__main__':
    main()
