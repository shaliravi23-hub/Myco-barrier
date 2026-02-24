#!/usr/bin/env python3
# ryu_myco_controller.py
#
# Ryu OF1.3 controller with:
# - L2 learning switch baseline
# - Control-plane latency (Echo RTT) logging
# - REST API to trigger strategy events in synchronized windows
# - Realistic strategy actions:
#   * Myco-Scout: isolate infected host (drop to/from)
#   * Myco-Box: quarantine by redirecting host-destined flows to sandbox proxy (per-edge)
#   * Myco-Swap: virtual proxy replacement (ARP steering + bidirectional rewrite)
#
# Requires: ryu, webob
#
# Run (example):
#   ryu-manager ryu_myco_controller.py --ofp-tcp-listen-port 6633

import json
import os
import time
from datetime import datetime
from typing import Dict, Any, Optional

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4
from ryu.lib import hub

from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from webob import Response

OUTDIR = os.environ.get("MYCO_OUTDIR", "myco_logs")
os.makedirs(OUTDIR, exist_ok=True)

MAPPING_PATH = os.environ.get("MYCO_MAPPING", "/tmp/myco_mapping.json")

ECHO_HZ = float(os.environ.get("MYCO_ECHO_HZ", "1.0"))  # echo sampling rate

REST_INSTANCE_NAME = "myco_rest_api"


def utc_iso():
    return datetime.utcnow().isoformat()


def load_mapping(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"hosts": [], "proxies": []}


class MycoRestController(ControllerBase):
    """
    REST endpoints:
      POST /myco/event
        body: {"strategy": "myco_scout|myco_box|myco_swap",
               "target_ip": "10.0.0.7",
               "duration_s": 8}
    """
    def __init__(self, req, link, data, **config):
        super().__init__(req, link, data, **config)
        self.myco_app = data["myco_app"]

    @route("myco", "/myco/event", methods=["POST"])
    def post_event(self, req, **kwargs):
        try:
            body = req.json if req.body else {}
        except Exception:
            body = {}

        strategy = str(body.get("strategy", "")).strip().lower()
        target_ip = str(body.get("target_ip", "")).strip()
        duration_s = float(body.get("duration_s", 8))

        if strategy not in ("myco_scout", "myco_box", "myco_swap"):
            return Response(status=400, body=b"Invalid strategy")
        if not target_ip:
            return Response(status=400, body=b"Missing target_ip")
        if duration_s <= 0 or duration_s > 120:
            return Response(status=400, body=b"Invalid duration_s")

        ok, msg = self.myco_app.trigger_event(strategy, target_ip, duration_s)
        if not ok:
            return Response(status=400, body=msg.encode("utf-8"))

        return Response(content_type="application/json",
                        body=json.dumps({"ok": True, "msg": msg}).encode("utf-8"))


class MycoBarrierController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        wsgi = kwargs["wsgi"]
        wsgi.register(MycoRestController, {REST_INSTANCE_NAME: {"myco_app": self}})

        self.mac_to_port: Dict[int, Dict[str, int]] = {}
        self.datapaths: Dict[int, Any] = {}

        # mapping
        self.mapping = load_mapping(MAPPING_PATH)
        self.host_by_ip = {h["ip"]: h for h in self.mapping.get("hosts", []) if "ip" in h}
        # proxies keyed by edge-switch dpid (integer)
        self.proxies_by_dpid: Dict[int, Any] = {}
        for p in self.mapping.get("proxies", []):
            self.proxies_by_dpid.setdefault(int(p["dpid"]), []).append(p)

        # Event state: only one active event at a time for clean comparability
        self.active_event: Optional[Dict[str, Any]] = None
        self.event_lock = hub.Semaphore(1)

        # Control-plane latency via Echo RTT
        self._echo_sent = {}  # (dpid, xid)->send_ts
        self._xid = 1
        self.ctrl_csv = os.path.join(OUTDIR, "ctrl_latency.csv")
        self.event_csv = os.path.join(OUTDIR, "events.csv")
        self._init_logs()

        self._echo_thread = hub.spawn(self._echo_loop)

        self.logger.info("MycoBarrierController ready. Mapping=%s OUTDIR=%s", MAPPING_PATH, OUTDIR)

    def _init_logs(self):
        if not os.path.exists(self.ctrl_csv):
            with open(self.ctrl_csv, "w", encoding="utf-8") as f:
                f.write("ts,dpid,rtt_ms\n")
        if not os.path.exists(self.event_csv):
            with open(self.event_csv, "w", encoding="utf-8") as f:
                f.write("ts,event,strategy,target_ip,target_mac,target_dpid,proxy_ip,proxy_mac,proxy_port,duration_s\n")

    # ---------------- OpenFlow basic plumbing ----------------

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser

        self.datapaths[dp.id] = dp
        self.mac_to_port.setdefault(dp.id, {})

        # Table-miss: send to controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, priority=0, match=match, actions=actions)

        self.logger.info("Switch connected: dpid=%s", dp.id)

    def _add_flow(self, dp, priority, match, actions, idle_timeout=0, hard_timeout=0):
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                instructions=inst, idle_timeout=idle_timeout,
                                hard_timeout=hard_timeout)
        dp.send_msg(mod)

    def _del_flows_by_cookie(self, dp, cookie):
        """Delete flows matching cookie (used to clean up after event)."""
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        mod = parser.OFPFlowMod(datapath=dp,
                                command=ofp.OFPFC_DELETE,
                                out_port=ofp.OFPP_ANY,
                                out_group=ofp.OFPG_ANY,
                                cookie=cookie,
                                cookie_mask=0xFFFFFFFFFFFFFFFF,
                                match=parser.OFPMatch())
        dp.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        dpid = dp.id

        in_port = msg.match["in_port"]
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return

        # Handle ARP steering for Myco-Swap and Myco-Box
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt is not None:
            self._handle_arp(dp, in_port, eth, arp_pkt)
            return

        src = eth.src
        dst = eth.dst
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofp.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]
        match = parser.OFPMatch(in_port=in_port, eth_src=src, eth_dst=dst)

        if out_port != ofp.OFPP_FLOOD:
            self._add_flow(dp, priority=10, match=match, actions=actions, idle_timeout=30)

        data = None
        if msg.buffer_id == ofp.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        dp.send_msg(out)

    # ---------------- ARP steering ----------------

    def _handle_arp(self, dp, in_port, eth, arp_pkt):
        """
        If Myco-Box or Myco-Swap event active and ARP request is for target_ip,
        respond with proxy MAC (so clients send to proxy while targeting same IP).
        """
        if arp_pkt.opcode != arp.ARP_REQUEST:
            return

        if not self.active_event:
            return

        target_ip = self.active_event["target_ip"]
        if arp_pkt.dst_ip != target_ip:
            return

        # respond with proxy MAC (virtual replacement)
        proxy_mac = self.active_event.get("proxy_mac")
        if not proxy_mac:
            return

        parser = dp.ofproto_parser
        ofp = dp.ofproto

        e = ethernet.ethernet(dst=eth.src, src=proxy_mac, ethertype=ether.ETH_TYPE_ARP)
        a = arp.arp(opcode=arp.ARP_REPLY,
                    src_mac=proxy_mac, src_ip=target_ip,
                    dst_mac=arp_pkt.src_mac, dst_ip=arp_pkt.src_ip)
        p = packet.Packet()
        p.add_protocol(e)
        p.add_protocol(a)
        p.serialize()

        actions = [parser.OFPActionOutput(in_port)]
        out = parser.OFPPacketOut(datapath=dp, buffer_id=ofp.OFP_NO_BUFFER,
                                  in_port=ofp.OFPP_CONTROLLER, actions=actions, data=p.data)
        dp.send_msg(out)

    # ---------------- Control-plane latency (Echo RTT) ----------------

    def _echo_loop(self):
        while True:
            for dpid, dp in list(self.datapaths.items()):
                try:
                    self._send_echo(dp)
                except Exception:
                    pass
            hub.sleep(max(0.01, 1.0 / ECHO_HZ))

    def _send_echo(self, dp):
        parser = dp.ofproto_parser
        xid = self._xid
        self._xid += 1
        self._echo_sent[(dp.id, xid)] = time.time()
        req = parser.OFPEchoRequest(dp, data=str(xid).encode("ascii"))
        dp.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER)
    def echo_reply(self, ev):
        dp = ev.msg.datapath
        dpid = dp.id
        try:
            xid = int(ev.msg.data.decode("ascii"))
        except Exception:
            return
        key = (dpid, xid)
        if key not in self._echo_sent:
            return
        rtt_ms = (time.time() - self._echo_sent.pop(key)) * 1000.0
        with open(self.ctrl_csv, "a", encoding="utf-8") as f:
            f.write(f"{utc_iso()},{dpid},{rtt_ms:.3f}\n")

    # ---------------- Strategy event orchestration ----------------

    def trigger_event(self, strategy: str, target_ip: str, duration_s: float):
        if target_ip not in self.host_by_ip:
            return False, f"Unknown target_ip: {target_ip}"

        # enforce single active event for clean comparability
        with self.event_lock:
            if self.active_event is not None:
                return False, "Another event is active; wait for it to finish."

            target = self.host_by_ip[target_ip]
            target_mac = target["mac"]
            target_dpid = int(target["dpid"])

            proxy = None
            proxy_ip = proxy_mac = proxy_port = ""
            if strategy in ("myco_box", "myco_swap"):
                candidates = self.proxies_by_dpid.get(target_dpid, [])
                if not candidates:
                    return False, f"No proxy attached to target edge switch dpid={target_dpid}"
                proxy = candidates[0]
                proxy_ip = proxy["ip"]
                proxy_mac = proxy["mac"]
                proxy_port = int(proxy["port"])

            self.active_event = {
                "strategy": strategy,
                "target_ip": target_ip,
                "target_mac": target_mac,
                "target_dpid": target_dpid,
                "proxy_ip": proxy_ip,
                "proxy_mac": proxy_mac,
                "proxy_port": proxy_port,
                "duration_s": duration_s,
                "cookie": int(time.time() * 1000)  # cookie for cleanup
            }

            self._log_event("start")
            self._apply_strategy_start()
            hub.spawn(self._auto_end_event)

            return True, f"Event started strategy={strategy} target={target_ip} duration={duration_s}s"

    def _auto_end_event(self):
        hub.sleep(self.active_event["duration_s"])
        with self.event_lock:
            if self.active_event is None:
                return
            self._cleanup_event()
            self._log_event("end")
            self.active_event = None

    def _log_event(self, evname: str):
        e = self.active_event
        with open(self.event_csv, "a", encoding="utf-8") as f:
            f.write(",".join([
                utc_iso(),
                evname,
                e["strategy"],
                e["target_ip"],
                e["target_mac"],
                str(e["target_dpid"]),
                str(e.get("proxy_ip", "")),
                str(e.get("proxy_mac", "")),
                str(e.get("proxy_port", "")),
                str(e["duration_s"])
            ]) + "\n")

    def _apply_strategy_start(self):
        s = self.active_event["strategy"]
        if s == "myco_scout":
            self._myco_scout_isolate()
        elif s == "myco_box":
            self._myco_box_quarantine()
        elif s == "myco_swap":
            self._myco_swap_replace()

    def _cleanup_event(self):
        # delete flows by cookie on all switches
        cookie = self.active_event["cookie"]
        for dp in list(self.datapaths.values()):
            try:
                self._del_flows_by_cookie(dp, cookie)
            except Exception:
                pass

    # ---------------- Implementations ----------------

    def _myco_scout_isolate(self):
        """
        Myco-Scout: hard isolation (drop to/from target IP) across fabric.
        """
        e = self.active_event
        target_ip = e["target_ip"]
        cookie = e["cookie"]

        for dp in list(self.datapaths.values()):
            parser = dp.ofproto_parser

            # Drop traffic destined to target
            match1 = parser.OFPMatch(eth_type=0x0800, ipv4_dst=target_ip)
            self._flow_with_cookie(dp, cookie, priority=300, match=match1, actions=[])

            # Drop traffic sourced from target (containment)
            match2 = parser.OFPMatch(eth_type=0x0800, ipv4_src=target_ip)
            self._flow_with_cookie(dp, cookie, priority=300, match=match2, actions=[])

    def _myco_box_quarantine(self):
        """
        Myco-Box: quarantine by diverting inbound traffic for target IP to sandbox proxy port
        on the same edge switch as the target.
        Return traffic is allowed from proxy but can be rewritten to preserve app flow.
        """
        e = self.active_event
        dp = self.datapaths.get(e["target_dpid"])
        if dp is None:
            return
        parser = dp.ofproto_parser

        target_ip = e["target_ip"]
        proxy_ip = e["proxy_ip"]
        proxy_mac = e["proxy_mac"]
        proxy_port = e["proxy_port"]
        cookie = e["cookie"]

        # Inbound to target -> redirect into sandbox (proxy)
        match_in = parser.OFPMatch(eth_type=0x0800, ipv4_dst=target_ip)
        actions_in = [
            parser.OFPActionSetField(ipv4_dst=proxy_ip),
            parser.OFPActionSetField(eth_dst=proxy_mac),
            parser.OFPActionOutput(proxy_port)
        ]
        self._flow_with_cookie(dp, cookie, priority=320, match=match_in, actions=actions_in)

        # Outbound from sandbox -> keep its identity (Box acts like sink), but allow forwarding
        # (no rewrite needed for quarantine; if you want full continuity, use Myco-Swap)
        # We still install a permissive rule so sandbox traffic isn’t accidentally dropped.
        match_out = parser.OFPMatch(eth_type=0x0800, ipv4_src=proxy_ip)
        actions_out = []  # let L2 learning handle; keep empty means DROP, so we must NOT do that.
        # For OF, "no match" falls to table-miss -> controller -> L2 learning.
        # We do not install a drop here.

    def _myco_swap_replace(self):
        """
        Myco-Swap: virtual proxy replacement so clients keep targeting target IP.
        Mechanisms:
          1) ARP steering: controller replies to ARP for target IP with proxy MAC.
          2) Inbound rewrite: dst IP/MAC rewritten to proxy.
          3) Outbound rewrite: src IP/MAC rewritten from proxy back to target identity.
        """
        e = self.active_event
        dp = self.datapaths.get(e["target_dpid"])
        if dp is None:
            return
        parser = dp.ofproto_parser

        target_ip = e["target_ip"]
        target_mac = e["target_mac"]
        proxy_ip = e["proxy_ip"]
        proxy_mac = e["proxy_mac"]
        proxy_port = e["proxy_port"]
        cookie = e["cookie"]

        # (A) Inbound to target IP -> rewrite to proxy and output to proxy port
        match_in = parser.OFPMatch(eth_type=0x0800, ipv4_dst=target_ip)
        actions_in = [
            parser.OFPActionSetField(ipv4_dst=proxy_ip),
            parser.OFPActionSetField(eth_dst=proxy_mac),
            parser.OFPActionOutput(proxy_port)
        ]
        self._flow_with_cookie(dp, cookie, priority=340, match=match_in, actions=actions_in)

        # (B) Outbound from proxy port with src=proxy_ip -> rewrite identity to target
        # so clients believe it is still the original host.
        match_out = parser.OFPMatch(eth_type=0x0800, in_port=proxy_port, ipv4_src=proxy_ip)
        actions_out = [
            parser.OFPActionSetField(ipv4_src=target_ip),
            parser.OFPActionSetField(eth_src=target_mac),
            # output decision: rely on L2 learning (controller) if unknown; thus send to controller
            parser.OFPActionOutput(dp.ofproto.OFPP_CONTROLLER, dp.ofproto.OFPCML_NO_BUFFER)
        ]
        self._flow_with_cookie(dp, cookie, priority=340, match=match_out, actions=actions_out)

    def _flow_with_cookie(self, dp, cookie, priority, match, actions, hard_timeout=0):
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                instructions=inst, cookie=cookie, cookie_mask=0xFFFFFFFFFFFFFFFF,
                                hard_timeout=hard_timeout)
        dp.send_msg(mod)
