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

def check_dependencies():
    if shutil.which("iperf") is None:
        print("\n[ERROR] 'iperf' is not installed. Please run: sudo apt-get install iperf\n")
        sys.exit(1)

def parse_iperf(server_log):
    # Regex for Bandwidth (Mbits/sec)
    bw_match = re.search(r'(\d+\.?\d*) ([KM])bits/sec', server_log)
    if bw_match:
        val = float(bw_match.group(1))
        unit = bw_match.group(2)
        bw = val if unit == 'M' else val / 1000.0
    else:
        bw = 0.0

    # Regex for Packet Loss
    loss_match = re.search(r'(\d+\.?\d*)% packet loss', server_log)
    loss = float(loss_match.group(1)) if loss_match else 100.0
    
    return bw, (100.0 - loss)

def run_test():
    check_dependencies()
    cleanup()
    
    info( '\n[SETUP] Building Topology with Static MACs...\n' )
    net = Mininet(controller=Controller, link=TCLink, switch=OVSKernelSwitch)
    net.addController('c0')
    s1 = net.addSwitch('s1')
    
    # 1. Define Hosts with STATIC MAC addresses to avoid "NoneType" errors
    # h1 (Client):  00:00:00:00:00:01
    # h2 (Server):  00:00:00:00:00:02
    # h3 (Sandbox): 00:00:00:00:00:03
    h1 = net.addHost('h1', ip='10.0.0.1', mac='00:00:00:00:00:01')
    h2 = net.addHost('h2', ip='10.0.0.2', mac='00:00:00:00:00:02')
    h3 = net.addHost('h3', ip='10.0.0.3', mac='00:00:00:00:00:03')
    
    # Link setup
    net.addLink(h1, s1, bw=10, delay='5ms') # Port 1
    net.addLink(h2, s1, bw=10, delay='5ms') # Port 2
    net.addLink(h3, s1, bw=10, delay='5ms') # Port 3
    
    net.start()
    net.pingAll() # Populate ARP tables
    
    strategies = ["Myco-Scout", "Myco-Box", "Myco-Swap"]
    
    print("\n" + "="*70)
    print(f"{'STRATEGY':<15} | {'LATENCY (ms)':<15} | {'THROUGHPUT':<15} | {'PDR (%)':<15}")
    print("="*70)
    
    for strat in strategies:
        # Clear old rules
        s1.dpctl('del-flows', 'priority=1000')
        
        # --- PHASE 1: LATENCY MEASUREMENT ---
        start_t = time.perf_counter()
        
        if strat == "Myco-Scout":
            # Action: DROP
            s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=drop')
            
        elif strat == "Myco-Box":
            # Action: Redirect to Sandbox (Port 3, MAC 03, IP 10.0.0.3)
            # We rewrite headers so h3 accepts the packet
            action = "mod_dl_dst:00:00:00:00:00:03,mod_nw_dst:10.0.0.3,output:3"
            s1.dpctl('add-flow', f'priority=1000,in_port=1,actions={action}')
            
        elif strat == "Myco-Swap":
            # Action: Forward to Normal Server (Port 2)
            s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=output:2')
            
        end_t = time.perf_counter()
        latency = (end_t - start_t) * 1000
        
        # --- PHASE 2: THROUGHPUT MEASUREMENT ---
        s1.dpctl('del-flows', 'priority=1000') # Reset
        
        # Determine Target Host
        target = h3 if strat == "Myco-Box" else h2
        
        # Start Server (kill old instances first)
        target.cmd('killall -9 iperf')
        target.cmd('iperf -s -u -i 1 > server.log &')
        time.sleep(2) 
        
        # Start Client Traffic (Always aiming at 10.0.0.2)
        h1.cmd('iperf -c 10.0.0.2 -u -t 5 -b 2M &')
        
        time.sleep(1.5)
        # Apply Strategy Mid-Stream
        if strat == "Myco-Scout":
            s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=drop')
        elif strat == "Myco-Box":
            action = "mod_dl_dst:00:00:00:00:00:03,mod_nw_dst:10.0.0.3,output:3"
            s1.dpctl('add-flow', f'priority=1000,in_port=1,actions={action}')
        elif strat == "Myco-Swap":
            s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=output:2')

        time.sleep(4.5)
        
        # Read Logs
        log = target.cmd('cat server.log')
        bw, pdr = parse_iperf(log)
        
        print(f"{strat:<15} | {latency:<15.4f} | {bw:<15.2f} | {pdr:<15.2f}")
        
    net.stop()
    cleanup()

if __name__ == '__main__':
    setLogLevel('error')
    run_test()
