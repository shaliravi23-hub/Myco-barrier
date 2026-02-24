#!/usr/bin/python3

import time
import os
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch, Host
from mininet.link import TCLink
from mininet.topo import Topo
from mininet.log import setLogLevel, info

class MycoIoTTopo(Topo):
    def build(self, n=50):
        # Standard Tree Topology
        core_switch = self.addSwitch('s1')
        agg_switches = []
        for i in range(1, 6):
            sw = self.addSwitch(f's10{i}')
            agg_switches.append(sw)
            self.addLink(sw, core_switch, bw=10, delay='5ms', use_htb=True)

        for i in range(1, n + 1):
            host = self.addHost(f'h{i}')
            switch_idx = (i - 1) // 10
            parent_switch = agg_switches[switch_idx]
            self.addLink(host, parent_switch, bw=10, delay='5ms', use_htb=True)

def run_mixed_scenario(net):
    info(f"\n*** Starting Mixed Scenario: 40 Legitimate vs 10 Attackers ***\n")
    
    # Wait for controller to learn topology
    time.sleep(5)

    hosts = net.hosts
    server = hosts[0] # h1 is the Gateway/Sink
    
    # SPLIT THE NETWORK
    # Hosts h2-h40 are GOOD (Sensors sending light data)
    legitimate_hosts = hosts[1:40]
    # Hosts h41-h50 are BAD (Botnet sending floods)
    attacker_hosts = hosts[40:]

    info(f"*** Gateway: {server.name} \n")
    info(f"*** Legitimate Nodes: {len(legitimate_hosts)} (Sending 50kbps - Safe) \n")
    info(f"*** Attacker Nodes:   {len(attacker_hosts)} (Sending 2Mbps - Malicious) \n")

    # Start Server (Log to CSV for parsing)
    server.cmd('iperf -s -u -i 1 -y C > iperf_server_log.txt &')

    # 1. Start LEGITIMATE Traffic (Should pass)
    info("*** Starting Sensor Traffic...\n")
    for h in legitimate_hosts:
        h.cmd(f'iperf -c {server.IP()} -u -b 50k -t 30 &')

    # 2. Start ATTACKER Traffic (Should be blocked)
    time.sleep(2)
    info("*** Unleashing Botnet Attack... ***\n")
    for h in attacker_hosts:
        h.cmd(f'iperf -c {server.IP()} -u -b 2M -t 25 &')
    
    # Progress Bar
    for _ in range(30):
        time.sleep(1)
        print('.', end='', flush=True)
    print()

    # --- METRICS ANALYSIS ---
    info("\n*** Analyzing Differentiated PDR... \n")
    server.cmd('killall -9 iperf')
    
    legit_sent = 0
    legit_lost = 0
    attack_sent = 0
    attack_lost = 0

    try:
        # Read the log file
        with open('iperf_server_log.txt', 'r') as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) > 12:
                    sender_ip = parts[1]
                    lost = int(parts[10])
                    total = int(parts[11])
                    
                    # Extract host ID from IP (e.g., 10.0.0.42 -> 42)
                    try:
                        host_id = int(sender_ip.split('.')[-1])
                    except:
                        continue
                    
                    if host_id <= 40: # Legitimate Range
                        legit_sent += total
                        legit_lost += lost
                    else: # Attacker Range
                        attack_sent += total
                        attack_lost += lost

        # Calculate Results
        legit_pdr = 100 * (1 - (legit_lost / legit_sent)) if legit_sent > 0 else 0
        attack_pdr = 100 * (1 - (attack_lost / attack_sent)) if attack_sent > 0 else 0

        info(f"\n================================================\n")
        info(f" FINAL RESULTS (Myco-Barrier Effectiveness)     \n")
        info(f"================================================\n")
        info(f"1. Legitimate Users PDR: {legit_pdr:.2f}%  (Target: >80%)\n")
        info(f"2. Attackers PDR:        {attack_pdr:.2f}%  (Target: <10%)\n")
        info(f"================================================\n")

    except Exception as e:
        info(f"Error parsing logs: {e}\n")

if __name__ == '__main__':
    setLogLevel('info')
    # Connect to your Ryu Controller
    c0 = RemoteController('c0', ip='127.0.0.1', port=6653)
    topo = MycoIoTTopo(n=50)
    net = Mininet(topo=topo, link=TCLink, controller=c0, switch=OVSKernelSwitch, host=Host, autoSetMacs=True)

    try:
        net.start()
        run_mixed_scenario(net)
    except Exception as e:
        info(f"Error: {e}\n")
    finally:
        net.stop()
        os.system('sudo mn -c > /dev/null 2>&1')
