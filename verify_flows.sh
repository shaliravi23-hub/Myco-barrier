#!/bin/bash
echo "Dumping Flow Table for Architectural Verification..."
sudo ovs-ofctl -O OpenFlow13 dump-flows s1

echo "Checking for SCOUT Meters..."
sudo ovs-ofctl -O OpenFlow13 dump-meters s1

echo "Checking for BOX VLAN Tags..."
sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep "push_vlan"

echo "Checking for SWAP Path Redirection..."
sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep "set_field:10.0.0.2"