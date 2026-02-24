import sys
import eventlet
# The Monkey Patch: Ryu needs this constant which was removed in newer eventlet versions
import eventlet.wsgi
if not hasattr(eventlet.wsgi, 'ALREADY_HANDLED'):
    eventlet.wsgi.ALREADY_HANDLED = None

# Now load Ryu
from ryu.cmd.manager import main

if __name__ == '__main__':
    # We pass the arguments manually here
    sys.argv = ['ryu-manager', 'ryu.app.simple_switch_13', '--ofp-tcp-listen-port', '6653']
    main()
