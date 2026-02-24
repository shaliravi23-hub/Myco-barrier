#!/usr/bin/python3
from mininet.topo import Topo
from mininet.link import TCLink

class MyTopo(Topo):
    "50 hosts connected to a single OVS switch (s1)."

    def build(self, N=50, bw=10, delay="5ms"):
        s1 = self.addSwitch("s1")

        for i in range(1, N + 1):
            h = self.addHost(f"h{i}")
            # Apply link constraints
            self.addLink(h, s1, cls=TCLink, bw=bw, delay=delay)

# Mininet looks for this dict when using --topo <name>
topos = {"mytopo": (lambda: MyTopo())}
