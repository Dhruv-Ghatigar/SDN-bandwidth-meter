import argparse
import os
import time
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--bw', type=float, default=10)
    p.add_argument('--delay', default='2ms')
    p.add_argument('--loss', type=float, default=0)
    p.add_argument('--auto', action='store_true')
    p.add_argument('--rates', type=int, nargs='+', default=[200, 1000, 4000])
    p.add_argument('--duration', type=float, default=10)
    a = p.parse_args()
    setLogLevel('info')
    net = Mininet(controller=RemoteController, switch=OVSKernelSwitch, link=TCLink, autoSetMacs=True)
    net.addController('c0', ip='127.0.0.1', port=6653)
    sw = net.addSwitch('s1', protocols='OpenFlow13')
    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    net.addLink(h1, sw, bw=a.bw, delay=a.delay, loss=a.loss)
    net.addLink(h2, sw, bw=a.bw, delay=a.delay, loss=a.loss)
    try:
        net.start()
        if a.auto:
            root = os.path.dirname(os.path.abspath(__file__))
            for name in ('send.csv', 'recv.csv'):
                path = os.path.join(root, name)
                if os.path.exists(path):
                    os.remove(path)
            h1.cmd('ping -c 2 10.0.0.2')
            time.sleep(3)
            for test_id, rate in enumerate(a.rates, 1):
                receiver = h2.popen(['python3', os.path.join(root, 'meter_complete.py'), 'recv', '--test-id', str(test_id), '--idle', '3', '--out', os.path.join(root, 'recv.csv')])
                time.sleep(1)
                h1.cmd('python3', os.path.join(root, 'meter_complete.py'), 'send', '--test-id', str(test_id), '--rate', str(rate), '--duration', str(a.duration), '--out', os.path.join(root, 'send.csv'))
                receiver.wait(timeout=a.duration + 10)
                time.sleep(3)
            print('Tests finished. Run compare_stats_complete.py from the project directory.')
        else:
            CLI(net)
    finally:
        net.stop()


if __name__ == '__main__':
    main()
