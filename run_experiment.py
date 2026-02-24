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
        h1 = self.addHost('h1', ip='10.0.0.1', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2', mac='00:00:00:00:00:02')
        h3 = self.addHost('h3', ip='10.0.0.3', mac='00:00:00:00:00:03')
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1)

def run_strategy(mode):
    print(f"\n=== RUNNING EXPERIMENT MODE: {mode} ===")
    
    env = os.environ.copy()
    env['MYCO_MODE'] = mode
    # Update this path if ryu-manager is elsewhere
    ryu_cmd = ["/home/vaishali/.local/bin/ryu-manager", "myco_controller_v2.py"]
    controller_proc = subprocess.Popen(ryu_cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3) 

    topo = MycoTopo()
    net = Mininet(topo=topo, controller=RemoteController, link=TCLink, switch=OVSKernelSwitch)
    net.start()
    
    h1, h2, h3 = net.get('h1', 'h2', 'h3')
    
    # Start Iperf Servers
    h1.cmd('iperf -s &')
    h2.cmd('iperf -s &') # Needed for SWAP mode redirection
    
    print(f"[{mode}] Running Legitimate Traffic & Logging Throughput...")
    # Client logs to CSV every 1 second
    h2.cmd(f'iperf -c 10.0.0.1 -t 35 -i 1 -y C > results_throughput_{mode}.csv &')
    
    time.sleep(10)
    
    print(f"[{mode}] Launching Attack...")
    h3.cmd('timeout 10s hping3 -S --flood -p 80 10.0.0.1 &')
    
    time.sleep(20) 
    
    print(f"[{mode}] Cleaning up...")
    net.stop()
    controller_proc.terminate() # cleaner than SIGTERM
    controller_proc.wait()
    subprocess.run(["mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == '__main__':
    setLogLevel('info')
    modes = ['BASELINE', 'SCOUT', 'BOX', 'SWAP']
    os.system("rm -f results_*.csv")
    
    for m in modes:
        run_strategy(m)
    print("\nExperiments complete.")
