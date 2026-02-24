from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI

class Myco50Topo(Topo):
    def build(self):
        # Central Switch supporting OpenFlow 1.3
        s1 = self.addSwitch('s1', cls=OVSSwitch, protocols='OpenFlow13')
        
        # h1: Target Server | h2: Standby Proxy | h99: Forensic Collector
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
        h99 = self.addHost('h99', ip='10.0.0.99/24', mac='00:00:00:00:00:99')
        
        self.addLink(h1, s1, cls=TCLink, bw=100)
        self.addLink(h2, s1, cls=TCLink, bw=100)
        self.addLink(h99, s1, cls=TCLink, bw=100, port2=99) # Fixed port for BOX

        # 47 Attack/Normal IoT Nodes
        for i in range(3, 51):
            h = self.addHost(f'h{i}', ip=f'10.0.0.{i}/24')
            self.addLink(h, s1, cls=TCLink, bw=10, delay='5ms')

def start_net():
    topo = Myco50Topo()
    net = Mininet(topo=topo, controller=RemoteController, link=TCLink)
    net.start()
    CLI(net)#!/bin/bash
STRATEGIES=("SCOUT" "BOX" "SWAP")

for STRAT in "${STRATEGIES[@]}"
do
    echo "--- TESTING STRATEGY: $STRAT ---"
    
    # 1. Start Controller in Background with the specific Strategy
    ryu-manager myco_architectural_controller.py --strategy $STRAT > logs/${STRAT}_controller.log 2>&1 &
    CPID=$!
    sleep 5
    
    # 2. Start Mininet and Run Attack in Background
    # Using 'screen' or '&' to run the attack inside the topology
    sudo python3 -c "
from mininet.net import Mininet
from myco_topo import Myco50Topo
from mininet.node import RemoteController
import time

net = Mininet(topo=Myco50Topo(), controller=RemoteController)
net.start()

print('Wait for Steady State (30s)...')
time.sleep(30)

print('LAUNCHING DDoS ATTACK (30s-75s)...')
target = '10.0.0.1'
for i in range(10, 30): # 20 Attackers
    attacker = net.get(f'h{i}')
    attacker.cmd(f'hping3 -S -p 80 --flood {target} &')

time.sleep(45) # Attack Duration
net.stop()
"
    
    # 3. Cleanup for next strategy
    kill $CPID
    sudo mn -c
    echo "--- $STRAT Completed ---"
    sleep 10
done
    net.stop()

if __name__ == '__main__':
    start_net()