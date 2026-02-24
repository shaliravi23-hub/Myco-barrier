from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI

class IoT_Topo(Topo):
    def build(self, n=50):
        switch = self.addSwitch('s1', dpid='0000000000000001')
        for i in range(1, n + 1):
            host = self.addHost(f'h{i}', ip=f'10.0.0.{i}', mac=f'00:00:00:00:00:{i:02x}')
            self.addLink(host, switch, port2=i) # Host h1 is on Port 1, h2 on Port 2...

if __name__ == '__main__':
    topo = IoT_Topo(n=50)
    net = Mininet(topo=topo, controller=RemoteController, switch=OVSSwitch, build=True)
    # Force OpenFlow 1.3
    for switch in net.switches:
        switch.cmd('ovs-vsctl set bridge s1 protocols=OpenFlow13')
    net.start()
    CLI(net)
    net.stop()
