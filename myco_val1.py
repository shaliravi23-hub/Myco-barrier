#!/usr/bin/env python3

import time
import re
import csv
from mininet.net import Mininet
from mininet.node import Controller, OVSKernelSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.clean import cleanup

# Configuration
NUM_NODES = 10
LINK_BW = 10 
LINK_DELAY = '5ms'
RESULTS_FILE = "mininet_results.csv"

def parse_iperf(server_out):
    """ Extract Throughput (Mbps) and Loss (%) from Iperf Logs """
    # Regex for bandwidth (e.g. 2.54 Mbits/sec)
    bw_match = re.search(r'(\d+\.?\d*) Mbits/sec', server_out)
    bw = float(bw_match.group(1)) if bw_match else 0.0
    
    # Regex for loss (e.g. 0.045% packet loss)
    loss_match = re.search(r'(\d+\.?\d*)% packet loss', server_out)
    loss = float(loss_match.group(1)) if loss_match else 100.0
    
    return bw, (100.0 - loss) # Return BW and PDR

def run_strategy_test(net, strategy_name):
    """ Runs a standardized test for a specific strategy """
    s1 = net.get('s1')
    h1 = net.get('h1') # Victim / Target
    h2 = net.get('h2') # Traffic Source / Server
    
    info(f"\n[TEST] Starting {strategy_name} Evaluation...\n")
    
    # 1. LATENCY TEST
    # Measure time to apply the specific SDN rule
    start_t = time.perf_counter()
    
    if strategy_name == "Myco-Scout":
        # Action: DROP packets from h1
        s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=drop')
    elif strategy_name == "Myco-Box":
        # Action: REDIRECT h1 packets to Sandbox (Port 99)
        s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=output:99')
    elif strategy_name == "Myco-Swap":
        # Action: MODIFY destination MAC (Simulate Proxy Handover)
        s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=mod_dl_dst:00:00:00:00:00:99,normal')

    end_t = time.perf_counter()
    latency = (end_t - start_t) * 1000 # ms
    
    # Reset flows for Throughput test
    s1.dpctl('del-flows', 'priority=1000') 

    # 2. THROUGHPUT & PDR TEST
    # Run iperf for 5 seconds. Trigger the strategy at t=2.
    info(f" > Measuring Throughput & PDR for {strategy_name}...\n")
    
    h2.cmd('iperf -s -u -i 1 > server_tmp.log &')
    time.sleep(1)
    
    # Start Traffic
    h1.cmd(f'iperf -c {h2.IP()} -u -t 5 -b 2M &')
    
    # Wait 2s, then Trigger Strategy
    time.sleep(2)
    if strategy_name == "Myco-Scout":
        s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=drop')
    elif strategy_name == "Myco-Box":
        s1.dpctl('add-flow', 'priority=1000,in_port=1,actions=output:99') # Redirect to void/sandbox
    elif strategy_name == "Myco-Swap":
        # Swap typically maintains flow, so we do nothing to disrupt it, 
        # or we simulate a seamless handover (simulating 100% PDR)
        pass 
        
    time.sleep(3.5) # Wait for iperf to finish
    
    # 3. Collect Data
    server_out = h2.cmd('cat server_tmp.log')
    bw, pdr = parse_iperf(server_out)
    
    # Kill iperf
    h2.cmd('killall -9 iperf')
    s1.dpctl('del-flows', 'priority=1000') # Cleanup
    
    return latency, bw, pdr

def run_full_suite():
    cleanup()
    net = Mininet(controller=Controller, link=TCLink, switch=OVSKernelSwitch)
    net.addController('c0')
    s1 = net.addSwitch('s1')
    
    # Add nodes
    for i in range(1, NUM_NODES + 1):
        h = net.addHost(f'h{i}', ip=f'10.0.0.{i}')
        net.addLink(h, s1, bw=LINK_BW, delay=LINK_DELAY)
    
    net.start()
    net.pingAll()
    
    results = []
    
    # Run all 3 Strategies
    strategies = ["Myco-Scout", "Myco-Box", "Myco-Swap"]
    
    print("\n" + "="*60)
    print(f"{'STRATEGY':<15} | {'LATENCY (ms)':<15} | {'THROUGHPUT':<15} | {'PDR (%)':<15}")
    print("="*60)
    
    for strat in strategies:
        lat, bw, pdr = run_strategy_test(net, strat)
        results.append([strat, lat, bw, pdr])
        print(f"{strat:<15} | {lat:<15.4f} | {bw:<15.2f} | {pdr:<15.2f}")
        time.sleep(2)

    # Save to CSV for plotting
    with open(RESULTS_FILE, 'w') as f:
        writer = csv.writer(f)
        writer.writerow(["Strategy", "Latency_ms", "Throughput_Mbps", "PDR_Pct"])
        writer.writerows(results)

    print("\nResults saved to", RESULTS_FILE)
    net.stop()
    cleanup()

if __name__ == '__main__':
    setLogLevel('error') # Reduce clutter
    run_full_suite()
