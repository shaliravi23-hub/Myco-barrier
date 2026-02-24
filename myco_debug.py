#!/usr/bin/env python3

import time
import re
import shutil
import sys
from mininet.net import Mininet
from mininet.node import Controller, OVSKernelSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.clean import cleanup

# ==========================================
# CONFIGURATION
# ==========================================
RESULTS_FILE = "mininet_fixed_results.csv"

def check_dependencies():
    """Ensure iperf is installed"""
    if shutil.which("iperf") is None:
        print("\n[ERROR] 'iperf' is not installed. Please run: sudo apt-get install iperf\n")
        sys.exit(1)

def parse_iperf(server_log):
    """Robust parser for Iperf output"""
    # Search for Bandwidth (Kbits or Mbits)
    bw_match = re.search(r'(\d+\.?\d*) ([KM])bits/sec', server_log)
    if bw_match:
        val = float(bw_match.group(1))
        unit = bw_match.group(2)
        bw = val if unit == 'M' else val / 1000.0 # Convert Kbits to Mbits
    else:
        bw = 0.0

    # Search for Packet Loss
    loss_match = re.search(r'(\d+\.?\d*)% packet loss', server_log)
    loss = float(loss_match.group(1)) if loss_match else 100.0
    
    return bw, (100.0 - loss)

def run_test():
    check_dependencies()
    cleanup()
    
    # 1. Setup Topology: h1 (Victim) -> s1 -> h2 (Server)
    #                                      -> h3 (Sandbox)
    info( '\n[SETUP] Building Topology...\n' )
    net = Mininet(controller=Controller, link=TCLink, switch=OVSKernelSwitch)
    net.addController('c0')
    s1 = net.addSwitch('s1')
    
    h1 = net.addHost('h1', ip='10.0.0.1') # Client
    h2 = net.addHost('h2', ip='10.0.0.2') # Normal Server
    h3 = net.addHost('h3', ip='10.0.0.3') # Sandbox
    
    net.addLink(h1, s1, bw=10, delay='5ms')
    net.addLink(h2, s1, bw=10, delay='5ms')
    net.addLink(h3, s1, bw=10, delay='5ms')
    
    net.start()
    net.pingAll() # Warm up ARP
    
    strategies = ["Myco-Scout", "Myco-Box", "Myco-Swap"]
    
    print("\n" + "="*70)
    print(f"{'STRATEGY':<15} | {'LATENCY (ms)':<15} | {'THROUGHPUT':<15} | {'PDR (%)':<15}")
    print("="*70)
    
    for strat in strategies:
        # Reset State
        s1.dpctl('del-flows', 'priority=1000')
        
        # --- PHASE 1: LATENCY MEASUREMENT ---
        start_t = time.perf_counter()
        if strat == "Myco-Scout":
            # Action: DROP
            s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=drop')
        elif strat == "Myco-Box":
            # Action: REDIRECT to Sandbox (Port 3 is h3)
            s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=output:3')
        elif strat == "Myco-Swap":
            # Action: Modify Header (Simulate Handover) + Forward Normal
            # We assume h2 is connected to Port 2. 
            # We explicitly enforce "output:2" to ensure connectivity.
            s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=mod_nw_tos:0x10,output:2')
            
        end_t = time.perf_counter()
        latency = (end_t - start_t) * 1000
        
        # --- PHASE 2: THROUGHPUT MEASUREMENT ---
        # Reset flows
        s1.dpctl('del-flows', 'priority=1000')
        
        # Identify Target Server
        # For Scout/Swap, we check h2 (Normal). 
        # For Box, we check h3 (Sandbox) because that's where traffic SHOULD go.
        target_host = h3 if strat == "Myco-Box" else h2
        
        # Start Server
        target_host.cmd('killall -9 iperf')
        target_host.cmd('iperf -s -u -i 1 > server.log &')
        time.sleep(1)
        
        # Start Client Traffic (5 seconds)
        # Send to h2 IP initially. 
        # (Myco-Box rule will redirect h2 IP packets to h3 physical port)
        h1.cmd(f'iperf -c 10.0.0.2 -u -t 5 -b 2M &')
        
        # Trigger Strategy in middle of stream
        time.sleep(1.5)
        if strat == "Myco-Scout":
            s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=drop')
        elif strat == "Myco-Box":
            s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=output:3') # Redirect to h3
        elif strat == "Myco-Swap":
            s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=mod_nw_tos:0x10,output:2')

        time.sleep(4.5) # Wait for finish
        
        # Collect Data
        log = target_host.cmd('cat server.log')
        bw, pdr = parse_iperf(log)
        
        # SPECIAL CASE: Myco-Scout SHOULD be 0. 
        # If it is 0, that is "Success" for isolation, but "Failure" for PDR metrics.
        # We report what iperf sees.
        
        print(f"{strat:<15} | {latency:<15.4f} | {bw:<15.2f} | {pdr:<15.2f}")
        
        # Debug: If 0.00 on Swap/Box, print log
        if strat in ["Myco-Swap", "Myco-Box"] and bw == 0.0:
            print(f"[DEBUG] Raw Log for {strat}:\n{log}")
            
    net.stop()
    cleanup()

if __name__ == '__main__':
    setLogLevel('error')
    run_test()
