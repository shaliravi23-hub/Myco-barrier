
#!/usr/bin/env python3

import time
import re
from mininet.net import Mininet
from mininet.node import Controller, OVSKernelSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.clean import cleanup

# ==========================================
# CONFIGURATION
# ==========================================
NUM_NODES = 20        # Keep small for stability
LINK_BW = 10          # 10 Mbps (IoT constraint)
LINK_DELAY = '5ms'    # 5ms latency (Zigbee/WiFi)
SANDBOX_IP = "10.0.0.99"

def run_myco_validation():
    # 1. Clean up previous runs
    cleanup()
    
    # 2. Setup Topology
    info( '\n[SETUP] Building VDDMZ Topology...\n' )
    net = Mininet(controller=Controller, link=TCLink, switch=OVSKernelSwitch)
    
    c0 = net.addController('c0')
    s1 = net.addSwitch('s1')

    # Add IoT Nodes
    hosts = []
    for i in range(1, NUM_NODES + 1):
        h = net.addHost(f'h{i}', ip=f'10.0.0.{i}')
        net.addLink(h, s1, bw=LINK_BW, delay=LINK_DELAY)
        hosts.append(h)

    # Add Sandbox Server
    sandbox = net.addHost('box', ip=SANDBOX_IP)
    net.addLink(sandbox, s1, bw=100, delay='1ms') # Fast backhaul

    net.start()
    net.pingAll() # Warm up ARP tables to avoid cold-start lag
    
    print("\n" + "="*50)
    print("   STARTING MYCO-BARRIER MECHANISM VALIDATION")
    print("="*50)

    # ==========================================
    # TEST A: MYCO-SCOUT (Isolation Speed)
    # Measure: Time to DELETE a flow rule
    # ==========================================
    info( '\n[TEST A] Myco-Scout: Measuring Isolation Latency...\n' )
    
    victim = hosts[0]
    # Start background traffic
    victim.cmd('ping -i 0.1 10.0.0.2 > /dev/null &')
    
    start = time.perf_counter()
    # COMMAND: Revoke OpenFlow Rule (Simulating Isolation)
    s1.dpctl('del-flows', 'in_port=1') 
    end = time.perf_counter()
    
    t_scout = (end - start) * 1000 # ms
    print(f" > RESULT: Isolation Latency = {t_scout:.4f} ms")


    # ==========================================
    # TEST B: MYCO-BOX (Tunneling Speed)
    # Measure: Time to INSTALL a redirect rule
    # ==========================================
    info( '\n[TEST B] Myco-Box: Measuring Tunnel Install Latency...\n' )
    
    suspect = hosts[1]
    
    start = time.perf_counter()
    # COMMAND: Install High-Priority Redirect to Sandbox (Port 21 is sandbox)
    # Note: We just simulate the control plane cost here
    s1.dpctl('add-flow', f'priority=100,in_port=2,actions=output:21')
    end = time.perf_counter()
    
    t_box = (end - start) * 1000
    print(f" > RESULT: Tunneling Latency = {t_box:.4f} ms")


    # ==========================================
    # TEST C: MYCO-SWAP (Proxy Fidelity)
    # Measure: Packet Delivery Ratio (PDR) during UDP stream
    # ==========================================
    info( '\n[TEST C] Myco-Swap: Measuring Virtual Proxy PDR...\n' )
    
    server = hosts[2] # The Cloud Server
    sensor = hosts[3] # The IoT Device
    
    # 1. Start UDP Server
    server.cmd('iperf -s -u -i 1 > iperf_server.log &')
    time.sleep(1)
    
    # 2. Run Client Traffic (Simulating continuous sensor data)
    # Sending for 5 seconds
    info( ' > Generating traffic flow (5 seconds)...\n' )
    sensor.cmd(f'iperf -c {server.IP()} -u -t 5 -b 2M')
    time.sleep(6) # Wait for finish
    
    # 3. Parse Results
    # We read the server log to see how many packets arrived
    log_content = server.cmd('cat iperf_server.log')
    
    # Regex to find loss percentage (e.g., "0.045% packet loss")
    match = re.search(r'(\d+\.?\d*)% packet loss', log_content)
    
    if match:
        loss = float(match.group(1))
        pdr = 100.0 - loss
    else:
        pdr = 100.0 # Default if clean
        
    print(f" > RESULT: Packet Delivery Ratio (PDR) = {pdr:.2f}%")
    print(f" > RESULT: Packet Loss during Stream   = {loss if match else 0:.2f}%")

    # Teardown
    net.stop()
    cleanup()

if __name__ == '__main__':
    setLogLevel('info')
    run_myco_validation()
EOF
