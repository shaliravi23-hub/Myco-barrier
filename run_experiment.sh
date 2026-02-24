#!/bin/bash
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