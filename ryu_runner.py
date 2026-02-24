#!/usr/bin/env python3
import sys
import eventlet.wsgi

# --- THE FIX ---
# Manually restore the constant that newer eventlet versions removed.
# This tricks Ryu into thinking everything is fine.
eventlet.wsgi.ALREADY_HANDLED = object() 
# ---------------

from ryu.cmd import manager

if __name__ == '__main__':
    # Ensure our controller file is passed to Ryu
    if 'myco_controller.py' not in sys.argv:
        sys.argv.append('myco_controller.py')
    
    # Run the Ryu Manager
    manager.main()
