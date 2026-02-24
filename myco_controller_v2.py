import os
import time
import psutil
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.lib import hub

class MycoFinalController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(MycoFinalController, self).__init__(*args, **kwargs)
        
        self.MODE = os.environ.get('MYCO_MODE', 'BASELINE') 
        self.logger.info(f"*** STARTING MYCO-CONTROLLER IN MODE: {self.MODE} ***")

        self.mac_to_port = {}
        self.packet_counts = {}
        self.server_load_counter = 0
        self.start_time = time.time()
        
        self.process = psutil.Process(os.getpid())
        self.monitor_thread = hub.spawn(self._resource_monitor)

    def _resource_monitor(self):
        """Logs Usage to CSV and forces disk write to prevent blank files."""
        log_file = f"results_resource_{self.MODE}.csv"
        with open(log_file, "w") as f:
            f.write("Time,CPU,RAM\n")
            f.flush()
            os.fsync(f.fileno())
            
        start_monitor = time.time()
        while True:
            hub.sleep(1)
            # interval=None is non-blocking
            cpu = self.process.cpu_percent(interval=None)
            mem = self.process.memory_info().rss / 1024 / 1024
            
            with open(log_file, "a") as f:
                f.write(f"{time.time()-start_monitor:.2f},{cpu},{mem:.2f}\n")
                f.flush()
                os.fsync(f.fileno())

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle=0, hard=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id or ofproto.OFP_NO_BUFFER,
                                priority=priority, match=match, instructions=inst,
                                idle_timeout=idle, hard_timeout=hard)
        datapath.send_msg(mod)

    def check_rate_limit(self, dpid, src):
        current_time = time.time()
        if current_time - self.start_time > 1.0:
            self.packet_counts = {}
            self.start_time = current_time
        
        self.packet_counts.setdefault(dpid, {})
        self.packet_counts[dpid].setdefault(src, 0)
        self.packet_counts[dpid][src] += 1
        return self.packet_counts[dpid][src] > 30

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP: return

        src, dst, dpid = eth.src, eth.dst, datapath.id
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        # --- STRATEGY SELECTION ---
        if self.MODE == 'SCOUT' and self.check_rate_limit(dpid, src):
            self.add_flow(datapath, 100, parser.OFPMatch(eth_src=src), [], hard=10)
            return

        elif self.MODE == 'BOX' and self.check_rate_limit(dpid, src):
            _ = [x**2 for x in range(5000)] # Simulated overhead
            self.add_flow(datapath, 100, parser.OFPMatch(eth_src=src), [], hard=10)
            return

        elif self.MODE == 'SWAP' and dst == "00:00:00:00:00:01":
            self.server_load_counter += 1
            if self.server_load_counter > 50:
                actions = [parser.OFPActionSetField(eth_dst="00:00:00:00:00:02"),
                           parser.OFPActionOutput(ofproto.OFPP_NORMAL)]
                self.add_flow(datapath, 50, parser.OFPMatch(in_port=in_port, eth_dst=dst), actions, idle=1, hard=1)
                out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                          in_port=in_port, actions=actions, data=msg.data)
                datapath.send_msg(out)
                return

        # --- FORWARDING ---
        out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]
        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
