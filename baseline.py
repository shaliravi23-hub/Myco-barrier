#!/usr/bin/python3

import time
import os
import random
import psutil
import subprocess
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch, Host
from mininet.link import TCLink
from mininet.topo import Topo
from mininet.log import setLogLevel, info

# --- CONFIGURATION ---
NUM_NODES = 50
DURATION = 100  # Seconds
CONTROLLER_IP = '127.0.0.1'

class BaselineTopo(Topo):
    def build(self, n=50):
        core_sw = self.addSwitch('s1')
        # 5 Aggregation switches for 50 nodes
        for i in range(1, 6):
            agg_sw = self.addSwitch(f's10{i}')
            self.addLink(agg_sw, core_sw, bw=10, delay='5ms')
            for j in range(1, 11):
                h_id = (i-1)*10 + j
                h = self.addHost(f'h{h_id}')
                self.addLink(h, agg_sw, bw=10, delay='5ms')

def get_ryu_pid():
    try:
        return int(subprocess.check_output(["pgrep", "-f", "ryu-manager"]).decode().split()[0])
    except:
        return None

def run_baseline():
    topo = BaselineTopo(n=NUM_NODES)
    net = Mininet(topo=topo, link=TCLink, controller=lambda name: RemoteController(name, ip=CONTROLLER_IP), autoSetMacs=True)
    net.start()
    
    info("*** Warming up (10s)...\n")
    time.sleep(10)
    
    server = net.get('h1')
    legit_nodes = [net.get(f'h{i}') for i in range(2, 41)] # h2-h40
    attackers = [net.get(f'h{i}') for i in range(41, 51)] # h41-h50
    
    # 1. Start Server for Throughput/PDR/Latency
    # -i 1 (1s interval), -u (UDP), -y C (CSV output)
    server.cmd('iperf -s -u -i 1 -y C > baseline_network_log.csv &')
    
    # 2. Start Legitimate Traffic (Background)
    for h in legit_nodes:
        h.cmd(f'iperf -c {server.IP()} -u -b 100k -t {DURATION} &')

    # 3. Monitoring Loop
    ryu_pid = get_ryu_pid()
    proc = psutil.Process(ryu_pid) if ryu_pid else None
    
    info(f"*** Recording Baseline for {DURATION}s (Check baseline_stats.csv)\n")
    
    with open('baseline_stats.csv', 'w') as f:
        f.write("timestamp,cpu_percent,mem_mb,attack_active\n")
        
        attack_start = random.randint(20, 40)
        attack_end = attack_start + 40
        attack_running = False

        for sec in range(DURATION):
            # Trigger Random Botnet Attack
            if sec == attack_start:
                info("\n*** BOTNET ATTACK START ***\n")
                attack_running = True
                for a in attackers:
                    a.cmd(f'iperf -c {server.IP()} -u -b 5M -t {attack_end - attack_start} &')
            
            if sec == attack_end:
                info("\n*** BOTNET ATTACK STOP ***\n")
                attack_running = False

            # Log Controller Metrics
            cpu = proc.cpu_percent(interval=None) if proc else 0
            mem = proc.memory_info().rss / (1024*1024) if proc else 0
            f.write(f"{sec},{cpu},{mem},{1 if attack_running else 0}\n")
            
            print('.', end='', flush=True)
            time.sleep(1)

    info("\n*** Baseline Finished. Cleaning up...\n")
    server.cmd('killall -9 iperf')
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    run_baseline()
