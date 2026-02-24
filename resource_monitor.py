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

class MycoUniversalController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(MycoUniversalController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        
        # =================================================================
        # [CRITICAL] SELECT YOUR STRATEGY HERE
        # Options: 'SCOUT', 'BOX', 'SWAP'
        # =================================================================
        self.STRATEGY = 'SWAP' 
        # =================================================================

        # --- CONFIGURATION ---
        self.INFECTION_RATE = 0.5       # 50% chance VPA fails
        self.DETECTION_THRESHOLD = 30   # Packets/sec to trigger isolation
        self.STRESS_THRESHOLD = 20      # Packets/sec to trigger Proxy (Scout/Box only)
        self.RECOVERY_TIME = 10         # Seconds
        
        # --- TOPOLOGY AWARENESS ---
        self.MAIN_SERVER_IP = "10.0.0.1"   # h1
        self.PROXY_NODE_IP = "10.0.0.2"    # h2 (The Standby Node)
        self.PROXY_MAC = "00:00:00:00:00:02" 
        
        # --- STATE MEMORY ---
        self.packet_counts = {}       
        self.quarantine_list = {}     # {mac: release_time}
        self.server_load_counter = 0  
        self.active_proxy_replacement = False # For Swap Mode
        self.start_time = time.time()

        # --- RESOURCE MONITORING ---
        self.process = psutil.Process(os.getpid())
        self.monitor_thread = hub.spawn(self._resource_monitor)

    def _resource_monitor(self):
        """ Logs Memory and CPU Usage with Attack-specific metrics """
        self.logger.info("Time(s), CPU(%), RAM(MB), Strategy, Proxy_Active, Under_Attack")
        
        start = time.time()
        # Track metrics during attack for final summary
        attack_cpu_samples = []
        attack_ram_samples = []

        while True:
            hub.sleep(2)
            
            # 1. Determine Attack Status
            # We are "Under Attack" if anyone is in quarantine OR if a proxy is active
            under_attack = "YES" if (len(self.quarantine_list) > 0 or self.active_proxy_replacement) else "NO"
            
            # 2. Get Standard Metrics
            cpu = self.process.cpu_percent(interval=None)
            mem_info = self.process.memory_info()
            ram_mb = mem_info.rss / 1024 / 1024 
            proxy_status = "YES" if (self.active_proxy_replacement or self.server_load_counter > self.STRESS_THRESHOLD) else "NO"
            
            # 3. Collect samples if under attack for internal calculation
            if under_attack == "YES":
                attack_cpu_samples.append(cpu)
                attack_ram_samples.append(ram_mb)
                
                # Optional: log a specific alert if CPU spikes during attack
                if cpu > 80:
                    self.logger.warning(f"!!! CRITICAL CPU SPIKE DURING ATTACK: {cpu}% !!!")

            # 4. Print detailed log line
            elapsed = time.time() - start
            print(f"{elapsed:.2f}, {cpu}, {ram_mb:.2f}, {self.STRATEGY}, {proxy_status}, {under_attack}")

            # 5. Periodic Attack Summary (Every 10 seconds if an attack is active)
            if under_attack == "YES" and int(elapsed) % 10 == 0 and attack_cpu_samples:
                avg_attack_cpu = sum(attack_cpu_samples) / len(attack_cpu_samples)
                avg_attack_ram = sum(attack_ram_samples) / len(attack_ram_samples)
                self.logger.info(f">>> ATTACK PHASE METRICS: Avg CPU: {avg_attack_cpu:.2f}%, Avg RAM: {avg_attack_ram:.2f}MB")

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
                                priority=priority, match=match,
                                instructions=inst, idle_timeout=idle, hard_timeout=hard)
        datapath.send_msg(mod)

    # --- CORE SECURITY LOGIC ---
    def check_security_status(self, src_mac):
        current_time = time.time()
        if src_mac in self.quarantine_list:
            release_time = self.quarantine_list[src_mac]
            if current_time < release_time:
                return 'DROP'
            
            # VPA Verification (All Strategies use this)
            if random.random() < self.INFECTION_RATE:
                self.logger.warning(f"XXX VPA FAILED: {src_mac} remains infected. XXX")
                self.quarantine_list[src_mac] += 5 
                return 'DROP'
            else:
                self.logger.info(f"*** VPA SUCCESS: {src_mac} reintegrated. ***")
                del self.quarantine_list[src_mac]
                # If we were in SWAP mode and the node recovers, we might disable Proxy
                if self.STRATEGY == 'SWAP': 
                    self.active_proxy_replacement = False 
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
        if eth.ethertype == ether_types.ETH_TYPE_LLDP: return

        src = eth.src
        dst = eth.dst
        dpid = datapath.id

        # 1. SECURITY CHECK (Barrier)
        status = self.check_security_status(src)
        if status == 'DROP': return 

        # 2. RATE LIMITING & DETECTION
        current_time = time.time()
        if current_time - self.start_time > 1.0:
            self.packet_counts = {}
            self.server_load_counter = 0 
            self.start_time = current_time
        
        self.packet_counts.setdefault(dpid, {})
        self.packet_counts[dpid].setdefault(src, 0)
        self.packet_counts[dpid][src] += 1

        # Check for ANOMALY (Attack Detection)
        if self.packet_counts[dpid][src] > self.DETECTION_THRESHOLD:
            self.logger.info(f"!!! ANOMALY DETECTED: {src} !!!")
            
            # --- STRATEGY DECISION POINT: ISOLATION HANDLING ---
            
            # Apply First Degree Isolation (ALL Strategies do this)
            self.quarantine_list[src] = time.time() + self.RECOVERY_TIME
            match = parser.OFPMatch(eth_src=src)
            self.add_flow(datapath, 100, match, [], hard=self.RECOVERY_TIME)
            
            # [CRITICAL CORRECTION]: MYCO-SWAP BEHAVIOR
            # "Immediate replacement by a proxy node happens at the moment of isolation"
            if self.STRATEGY == 'SWAP':
                if not self.active_proxy_replacement:
                    self.logger.info(">>> MYCO-SWAP TRIGGERED: Proxy Immediately Replacing Isolated Service >>>")
                    self.active_proxy_replacement = True
            
            return # Drop the bad packet

        # 3. TRAFFIC FORWARDING & PROXY USAGE
        
        # Determine actual destination based on Proxy State
        final_dst_mac = dst
        
        # [CRITICAL CORRECTION]: PROXY LOGIC DISTINCTION
        
        # CASE A: MYCO-SWAP (Failover Mode)
        # If Swap is active, ALL traffic to Main Server goes to Proxy
        if self.STRATEGY == 'SWAP' and self.active_proxy_replacement:
            if dst == "00:00:00:00:00:01": # If target is Main Server
                final_dst_mac = self.PROXY_MAC # Hijack to Proxy
        
        # CASE B: SCOUT / BOX (Stress/Load Mode)
        # If Load is High, send SOME traffic to Proxy
        elif self.STRATEGY in ['SCOUT', 'BOX']:
            if dst == "00:00:00:00:00:01":
                self.server_load_counter += 1
                if self.server_load_counter > self.STRESS_THRESHOLD:
                    # User said: "used when any active nodes are identified as stressed"
                    final_dst_mac = self.PROXY_MAC 
                    if self.server_load_counter == self.STRESS_THRESHOLD + 1:
                        self.logger.info(">>> STRESS DETECTED (Scout/Box): Offloading current packet to Proxy >>>")

        # 4. STANDARD LEARNING & SWITCHING
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        if final_dst_mac in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][final_dst_mac]
            actions = [parser.OFPActionOutput(out_port)]
            
            # If we swapped/redirected, we must rewrite the destination MAC in the packet
            if final_dst_mac != dst:
                 actions.insert(0, parser.OFPActionSetField(eth_dst=final_dst_mac))

            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            
            # Install Flow (Short idle time to allow dynamic updates)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id, idle=2)
                return
            else:
                self.add_flow(datapath, 1, match, actions, idle=2)
        else:
            out_port = ofproto.OFPP_FLOOD
            actions = [parser.OFPActionOutput(out_port)]

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
