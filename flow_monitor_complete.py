import csv
import os
import time
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.ofproto import ofproto_v1_3

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT_FILE = os.path.join(ROOT, 'sdn_port_stats.csv')
FLOW_FILE = os.path.join(ROOT, 'sdn_flow_stats.csv')
PORT_FIELDS = ['timestamp', 'dpid', 'port_no', 'rx_packets', 'tx_packets', 'rx_bytes', 'tx_bytes', 'rx_dropped', 'tx_dropped']
FLOW_FIELDS = ['timestamp', 'dpid', 'in_port', 'out_port', 'eth_dst', 'packet_count', 'byte_count']


def append(path, fields, rows):
    if not rows:
        return
    fresh = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if fresh:
            writer.writeheader()
        writer.writerows(rows)


class FlowMonitor(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.mac_to_port = {}
        hub.spawn(self.poll)

    def add_flow(self, dp, match, actions, priority):
        p = dp.ofproto_parser
        instructions = [p.OFPInstructionActions(dp.ofproto.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(p.OFPFlowMod(datapath=dp, priority=priority, match=match, instructions=instructions))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features(self, ev):
        dp = ev.msg.datapath
        p = dp.ofproto_parser
        self.add_flow(dp, p.OFPMatch(), [p.OFPActionOutput(dp.ofproto.OFPP_CONTROLLER, dp.ofproto.OFPCML_NO_BUFFER)], 0)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change(self, ev):
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[ev.datapath.id] = ev.datapath
        else:
            self.datapaths.pop(ev.datapath.id, None)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg = ev.msg
        dp = msg.datapath
        p = dp.ofproto_parser
        eth = packet.Packet(msg.data).get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        in_port = msg.match['in_port']
        table = self.mac_to_port.setdefault(dp.id, {})
        table[eth.src] = in_port
        out_port = table.get(eth.dst, dp.ofproto.OFPP_FLOOD)
        actions = [p.OFPActionOutput(out_port)]
        if out_port != dp.ofproto.OFPP_FLOOD:
            match = p.OFPMatch(in_port=in_port, eth_dst=eth.dst)
            self.add_flow(dp, match, actions, 10)
        dp.send_msg(p.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id, in_port=in_port, actions=actions, data=msg.data if msg.buffer_id == dp.ofproto.OFP_NO_BUFFER else None))

    def poll(self):
        while True:
            for dp in list(self.datapaths.values()):
                p = dp.ofproto_parser
                dp.send_msg(p.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY))
                dp.send_msg(p.OFPFlowStatsRequest(dp))
            hub.sleep(1)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats(self, ev):
        ts = time.time()
        rows = [dict(timestamp=ts, dpid=ev.msg.datapath.id, port_no=s.port_no, rx_packets=s.rx_packets, tx_packets=s.tx_packets, rx_bytes=s.rx_bytes, tx_bytes=s.tx_bytes, rx_dropped=s.rx_dropped, tx_dropped=s.tx_dropped) for s in ev.msg.body if s.port_no < 0xf0000000]
        append(PORT_FILE, PORT_FIELDS, rows)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats(self, ev):
        ts = time.time()
        rows = []
        for s in ev.msg.body:
            if s.priority != 10:
                continue
            actions = [a.port for i in s.instructions if hasattr(i, 'actions') for a in i.actions if hasattr(a, 'port')]
            rows.append(dict(timestamp=ts, dpid=ev.msg.datapath.id, in_port=s.match.get('in_port', ''), out_port=actions[0] if actions else '', eth_dst=s.match.get('eth_dst', ''), packet_count=s.packet_count, byte_count=s.byte_count))
        append(FLOW_FILE, FLOW_FIELDS, rows)
