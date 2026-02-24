import time
import random
import psutil
import os
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib import hub

class MycoFinalController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(MycoFinalController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        
        # --- CONFIGURATION ---
        self.INFECTION_RATE = 0.5       # 50% chance VPA fails
        self.DETECTION_THRESHOLD = 30   # Packets/sec to trigger isolation
        self.RECOVERY_TIME = 10         # Seconds
        self.LOAD_THRESHOLD = 50        # Packets/sec to trigger Proxy Swap
        
        # --- TOPOLOGY AWARENESS ---
        self.MAIN_SERVER_IP = "10.0.0.1"
        self.PROXY_NODE_IP = "10.0.0.2" # The Standby Node
        
        # --- STATE MEMORY ---
        self.packet_counts = {}       
        self.quarantine_list = {}     # {mac: release_time}
        self.server_load_counter = 0  # Track load on Main Server
        self.start_time = time.time()

        # --- RESOURCE MONITORING ---
        self.process = psutil.Process(os.getpid())
        self.monitor_thread = hub.spawn(self._resource_monitor)

    def _resource_monitor(self):
        """ Logs Memory and CPU Usage of this Strategy """
        self.logger.info("Time(s), CPU(%), RAM(MB), Active_Flows, Quarantined_Nodes")
        start = time.time()
        while True:
            hub.sleep(2) # Log every 2 seconds
            
            # 1. CPU Usage
            cpu = self.process.cpu_percent(interval=None)
            
            # 2. RAM Usage (Resident Set Size)
            mem_info = self.process.memory_info()
            ram_mb = mem_info.rss / 1024 / 1024 
            
            # 3. Logic Complexity Metrics
            q_size = len(self.quarantine_list)
            
            # CSV Format Output for easy graphing later
            print(f"{time.time()-start:.2f}, {cpu}, {ram_mb:.2f}, N/A, {q_size}")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle=0, hard=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        
        mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id or ofproto.OFP_NO_BUFFER,
                                priority=priority, match=match,
                                instructions=inst, idle_timeout=idle, hard_timeout=hard)
        datapath.send_msg(mod)

    # --- CORE SECURITY LOGIC (Myco-Barrier) ---
    def check_security_status(self, src_mac):
        """ Returns: 'ALLOW', 'DROP', or 'REINTEGRATE' """
        current_time = time.time()
        
        if src_mac in self.quarantine_list:
            release_time = self.quarantine_list[src_mac]
            
            if current_time < release_time:
                return 'DROP' # Timer still running
            
            # Timer Finished -> VPA Verification
            # 50% Chance of Failure (Infection Persistence)
            if random.random() < self.INFECTION_RATE:
                self.logger.warning(f"XXX VPA FAILED: {src_mac} remains infected. XXX")
                self.quarantine_list[src_mac] += 5 # Extend punishment
                return 'DROP'
            else:
                self.logger.info(f"*** VPA SUCCESS: {src_mac} reintegrated. ***")
                del self.quarantine_list[src_mac]
                return 'REINTEGRATE'
        
        return 'ALLOW'

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

        src = eth.src
        dst = eth.dst
        dpid = datapath.id

        # 1. SECURITY CHECK
        status = self.check_security_status(src)
        if status == 'DROP':
            return # Silent Drop

        # 2. RATE LIMITING (Anomaly Detection)
        current_time = time.time()
        if current_time - self.start_time > 1.0:
            # Reset counters every second
            self.packet_counts = {}
            self.server_load_counter = 0 # Reset Server Load too
            self.start_time = current_time
        
        self.packet_counts.setdefault(dpid, {})
        self.packet_counts[dpid].setdefault(src, 0)
        self.packet_counts[dpid][src] += 1

        if self.packet_counts[dpid][src] > self.DETECTION_THRESHOLD:
            self.logger.info(f"!!! ANOMALY: Isolating {src} (Rate: {self.packet_counts[dpid][src]}) !!!")
            # Add to Quarantine
            self.quarantine_list[src] = time.time() + self.RECOVERY_TIME
            # Push Hardware Drop Rule
            match = parser.OFPMatch(eth_src=src)
            self.add_flow(datapath, 100, match, [], hard=self.RECOVERY_TIME)
            return

        # 3. PROXY SWAP (Load Balancing)
        # Check if traffic is destined for Main Server
        # (Assuming we map '00:00:00:00:00:01' to Main Server for simulation simplicity)
        # or checking IP if we parsed ARP/IP packets. 
        # For this script, we assume h1 (Gateway) is the target.
        
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port
        
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
            
            # --- LOAD BALANCING LOGIC ---
            # If target is h1 (Server) and Load is High
            # Ideally, compare 'dst' MAC to h1's MAC. 
            # Here we assume h1 is on port 1 of s1 for simplicity or tracked via MAC.
            
            if dst == "00:00:00:00:00:01": # Example MAC for h1
                self.server_load_counter += 1
                if self.server_load_counter > self.LOAD_THRESHOLD:
                    # OFF-LOAD TO PROXY (h2 - 00:00:00:00:00:02)
                    # We rewrite the destination to the proxy node
                    # Note: This is a simplified "Redirect" for simulation.
                    actions = [parser.OFPActionSetField(eth_dst="00:00:00:00:00:02"),
                               parser.OFPActionOutput(ofproto.OFPP_NORMAL)] # Send to Proxy
                    
                    # Log it only once per second to avoid spam
                    if self.server_load_counter == self.LOAD_THRESHOLD + 1:
                        self.logger.info(">>> LOAD CRITICAL: Diverting traffic to Proxy Node (h2) >>>")
                    
                    # Install temporary redirect flow
                    match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
                    self.add_flow(datapath, 50, match, actions, idle=1, hard=1) 
                    
                    # Execute immediately
                    out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                              in_port=in_port, actions=actions, data=msg.data)
                    datapath.send_msg(out)
                    return

        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id, idle=5)
                return
            else:
                self.add_flow(datapath, 1, match, actions, idle=5)
        
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
