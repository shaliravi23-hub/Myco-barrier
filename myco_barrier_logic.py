import time
import random
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types

class MycoBarrierLogic(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(MycoBarrierLogic, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        
        # --- MYCO-BARRIER STATE MEMORY ---
        self.packet_counts = {}       # Traffic counter for detection
        self.quarantine_list = {}     # {mac: release_time} -> Handles Recovery Time
        self.vpa_verification_queue = set() # Nodes waiting for VPA check
        
        # CONFIGURATION
        self.DETECTION_THRESHOLD = 30 # Packets per second to trigger isolation
        self.RECOVERY_TIME = 10       # Seconds to stay in First Degree Isolation
        self.start_time = time.time()

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Table-Miss: Send unknown packets to Controller
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

    # ---------------------------------------------------------
    # FEATURE 1: FIRST DEGREE ISOLATION
    # ---------------------------------------------------------
    def isolate_node(self, datapath, src_mac):
        current_time = time.time()
        
        # If already isolated, ignore
        if src_mac in self.quarantine_list:
            return

        self.logger.warning(f"!!! MYCO-SCOUT DETECTED THREAT: {src_mac} !!!")
        self.logger.info(f"-> Activating First Degree Isolation on Port")

        # 1. Set Recovery Timer
        release_time = current_time + self.RECOVERY_TIME
        self.quarantine_list[src_mac] = release_time
        
        # 2. Push DROP Rule to Switch (High Priority)
        # We use a hard_timeout matching the recovery time so the switch 
        # automatically drops the rule when time is up, allowing the packet-in to resume.
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(eth_src=src_mac)
        actions = [] # Drop
        
        # Priority 100 (Higher than normal traffic)
        self.add_flow(datapath, 100, match, actions, hard=self.RECOVERY_TIME)

    # ---------------------------------------------------------
    # FEATURE 2 & 3: RECOVERY TIME & VPA VERIFICATION
    # ---------------------------------------------------------
    def check_reintegration(self, src_mac):
        """
        Checks if a node is allowed to recover.
        Returns True if allowed, False if still isolated.
        """
        if src_mac not in self.quarantine_list:
            return True # Not quarantined, allowed.

        current_time = time.time()
        release_time = self.quarantine_list[src_mac]

        # Is the Recovery Time over?
        if current_time > release_time:
            # Time is up, but we must run VPA Verification first
            if src_mac not in self.vpa_verification_queue:
                self.logger.info(f"-> Timer ended for {src_mac}. Initiating VPA Agent Verification...")
                self.vpa_verification_queue.add(src_mac)
                return False # Still blocked until verified
            
            # Simulate VPA Logic (Virtual Proxy Agent check)
            # In a real system, this would exchange crypto keys. 
            # Here, we simulate a 50% chance of pass/fail or just pass.
            is_clean = random.choice([True, True, True, False]) # 75% chance success
            
            if is_clean:
                self.logger.info(f"*** VPA VERIFICATION SUCCESS: Reintegrating {src_mac} ***")
                del self.quarantine_list[src_mac]
                self.vpa_verification_queue.remove(src_mac)
                return True
            else:
                self.logger.warning(f"xxx VPA VERIFICATION FAILED: {src_mac} stays isolated xxx")
                # Extend quarantine by 5 seconds
                self.quarantine_list[src_mac] += 5
                return False
        
        return False # Timer not up yet

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

        # --- STEP 1: CHECK QUARANTINE & VPA STATUS ---
        if not self.check_reintegration(src):
            return # Drop packet silently (Software Filtering)

        # --- STEP 2: MYCO-SCOUT DETECTION (Rate Limiting) ---
        current_time = time.time()
        if current_time - self.start_time > 1.0:
            self.packet_counts = {}
            self.start_time = current_time
        
        self.packet_counts.setdefault(dpid, {})
        self.packet_counts[dpid].setdefault(src, 0)
        self.packet_counts[dpid][src] += 1

        if self.packet_counts[dpid][src] > self.DETECTION_THRESHOLD:
            self.isolate_node(datapath, src)
            return
        # ----------------------------------------------------

        # --- STEP 3: STANDARD FORWARDING ---
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
