import os
import time
import subprocess
import signal
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.log import setLogLevel

class MycoTopo(Topo):
    def build(self):
        s1 = self.addSwitch('s1')
        h1 = self.addHost('h1', ip='10.0.0.1', mac='00:00:00:00:00:01') # Server
        h2 = self.addHost('h2', ip='10.0.0.2', mac='00:00:00:00:00:02') # Proxy / Legitimate
        h3 = self.addHost('h3', ip='10.0.0.3', mac='00:00:00:00:00:03') # Attacker
        
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1)

def run_strategy(mode):
    print(f"\n\n=== RUNNING EXPERIMENT MODE: {mode} ===")
    
    # 1. Start Ryu Controller in Background with ENV Variable
    env = os.environ.copy()
    env['MYCO_MODE'] = mode
    ryu_cmd = ["/home/vaishali/.local/bin/ryu-manager", "myco_controller_v2.py"]
    # We suppress output to keep console clean
    controller_proc = subprocess.Popen(ryu_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5) # Wait for controller to start

    # 2. Start Mininet
    topo = MycoTopo()
    net = Mininet(topo=topo, controller=RemoteController, link=TCLink, switch=OVSKernelSwitch)
    net.start()
    
    h1, h2, h3 = net.get('h1', 'h2', 'h3')
    
    # 3. Start Throughput Monitor (Iperf Server on h1)
    h1.cmd('iperf -s -i 1 > results_throughput_{}.csv &'.format(mode))
    
    # 4. Start Legitimate Traffic (h2 -> h1)
    print(f"[{mode}] Starting Legitimate Traffic...")
    h2.cmd('iperf -c 10.0.0.1 -t 40 &')
    
    time.sleep(10) # Let traffic stabilize
    
    # 5. Start Attack (h3 -> h1)
    # Using hping3 or a simple flood
    print(f"[{mode}] Launching Attack...")
    h3.cmd('timeout 15s hping3 -S --flood -V -p 80 10.0.0.1 &')
    
    # 6. Wait for Experiment to Finish
    time.sleep(20) # 15s attack + 5s recovery
    
    # 7. Cleanup
    print(f"[{mode}] Stopping...")
    net.stop()
    os.kill(controller_proc.pid, signal.SIGTERM)
    subprocess.run(["mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)

if __name__ == '__main__':
    setLogLevel('info')
    
    # Run all 4 modes sequentially
    modes = ['BASELINE', 'SCOUT', 'BOX', 'SWAP']
    
    # Clean old results
    os.system("rm results_*.csv")
    
    for m in modes:
        run_strategy(m)
        
    print("\nAll experiments complete. Run 'python3 plot_results.py' to generate graphs.")
