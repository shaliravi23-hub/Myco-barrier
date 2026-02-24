import time
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types

class MycoBoxController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(MycoBoxController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        
        # MYCO-BOX DEFENSE STRUCTURES
        self.packet_counts = {}   # {dpid: {mac: count}}
        self.blacklist = set()    # Set of banned MACs
        self.start_time = time.time()
        
        # Threshold: If a node sends > 20 packet-ins per second, isolate it.
        self.THRESHOLD = 20 

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Standard Table-Miss Flow
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst, idle_timeout=idle_timeout)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst, 
                                    idle_timeout=idle_timeout)
        datapath.send_msg(mod)

    def block_host(self, datapath, src_mac):
        """ The Myco-Box Isolation Logic """
        if src_mac in self.blacklist:
            return

        self.logger.warning(f"*** MYCO-BOX TRIGGERED: Isolating Suspect Node {src_mac} ***")
        self.blacklist.add(src_mac)
        
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # High Priority Drop Rule (Isolation)
        match = parser.OFPMatch(eth_src=src_mac)
        actions = [] # Empty actions = DROP
        
        # Add flow with higher priority (100) than normal traffic (1)
        # Set idle_timeout to 0 (permanent ban) or higher for temporary
        self.add_flow(datapath, 100, match, actions)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        # --- MYCO-BOX DETECTION LOGIC ---
        # 1. Reset counter every second (simple sliding window)
        current_time = time.time()
        if current_time - self.start_time > 1.0:
            self.packet_counts = {}
            self.start_time = current_time
            
        # 2. Count packets
        self.packet_counts.setdefault(dpid, {})
        self.packet_counts[dpid].setdefault(src, 0)
        self.packet_counts[dpid][src] += 1
        
        # 3. Check Threshold
        if self.packet_counts[dpid][src] > self.THRESHOLD:
            self.block_host(datapath, src)
            return # Stop processing this packet
            
        if src in self.blacklist:
            return # Don't forward packets from blacklisted hosts
        # -------------------------------

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self.add_flow(datapath, 1, match, actions)
        
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
