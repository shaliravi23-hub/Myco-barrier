#!/usr/bin/env python3
# mn_compare_myco.py
#
# Runs comparable experiments across:
#   myco_scout, myco_box, myco_swap
# Measures:
#   - Throughput (from iperf UDP interval lines)
#   - PDR (from iperf UDP loss summary)
#   - Control plane latency L_ctrl (from controller ctrl_latency.csv)
# Scalability:
#   - Sweep N (e.g., 10,20,30,40,50)

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from statistics import mean, pstdev

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.clean import cleanup

# -------- parsing helpers (iperf2 UDP) --------

UDP_SUMMARY_RE = re.compile(r"(?P<loss>\d+)\s*/\s*(?P<total>\d+)\s*\((?P<pct>[\d.]+)%\)")
INTERVAL_RE = re.compile(r"\s(?P<bw>[\d.]+)\s(?P<unit>[KMG])bits/sec")

def parse_iperf_client_log(text: str):
    series_bps = []
    for m in INTERVAL_RE.finditer(text):
        bw = float(m.group("bw"))
        unit = m.group("unit")
        mult = {"K": 1e3, "M": 1e6, "G": 1e9}[unit]
        series_bps.append(bw * mult)

    pdr = None
    for m in UDP_SUMMARY_RE.finditer(text):
        loss = int(m.group("loss"))
        total = int(m.group("total"))
        if total > 0:
            pdr = 1.0 - (loss / total)
    return series_bps, pdr

def mean_ctrl_latency_ms(ctrl_csv: Path):
    if not ctrl_csv.exists():
        return None
    vals = []
    with open(ctrl_csv, "r", encoding="utf-8") as f:
        next(f, None)  # header
        for line in f:
            parts = line.strip().split(",")
            if len(parts) != 3:
                continue
            try:
                vals.append(float(parts[2]))
            except Exception:
                pass
    return mean(vals) if vals else None

# -------- topology builder --------

def build_iot_topology(net: Mininet, n_hosts: int, n_edges: int, bw: int, delay_ms: int):
    """
    s1 core, s2..s{n_edges+1} edges
    Each edge gets:
      - 1 proxy pX (sandbox/proxy)
      - k hosts
    """
    core = net.addSwitch("s1", protocols="OpenFlow13")
    edges = []
    for i in range(n_edges):
        edges.append(net.addSwitch(f"s{i+2}", protocols="OpenFlow13"))

    # core-edge links
    for sw in edges:
        net.addLink(core, sw, cls=TCLink, bw=bw, delay=f"{delay_ms}ms", use_htb=True)

    # distribute hosts
    per_edge = n_hosts // n_edges
    rem = n_hosts % n_edges
    h_idx = 1
    hosts = []
    proxies = []

    for ei, sw in enumerate(edges):
        # proxy host on each edge
        p = net.addHost(f"p{ei+1}", ip=f"10.0.0.{250+ei+1}/24")
        proxies.append((p, sw))
        net.addLink(p, sw, cls=TCLink, bw=bw, delay=f"{delay_ms}ms", use_htb=True)

        count = per_edge + (1 if ei < rem else 0)
        for _ in range(count):
            h = net.addHost(f"h{h_idx}", ip=f"10.0.0.{h_idx}/24")
            hosts.append((h, sw))
            net.addLink(h, sw, cls=TCLink, bw=bw, delay=f"{delay_ms}ms", use_htb=True)
            h_idx += 1

    return core, edges, hosts, proxies

def dpid_int(sw):
    dpid_str = getattr(sw, "dpid", None)
    if dpid_str:
        try:
            return int(dpid_str, 16)
        except Exception:
            pass
    # fallback from name sX
    return int(sw.name.replace("s", ""))

def write_mapping_json(net: Mininet, hosts, proxies, out_path: Path):
    mapping = {"hosts": [], "proxies": []}

    for h, sw in hosts:
        hnode = net.get(h.name)
        swnode = net.get(sw.name)
        links = net.linksBetween(hnode, swnode)
        if not links:
            continue
        link = links[0]
        # switch interface on that link
        sw_intf = link.intf1 if link.intf1.node == swnode else link.intf2
        sw_port = swnode.ports[sw_intf]
        mapping["hosts"].append({
            "name": h.name,
            "role": "host",
            "ip": hnode.IP(),
            "mac": hnode.MAC(),
            "dpid": dpid_int(swnode),
            "port": int(sw_port),
        })

    for p, sw in proxies:
        pnode = net.get(p.name)
        swnode = net.get(sw.name)
        links = net.linksBetween(pnode, swnode)
        if not links:
            continue
        link = links[0]
        sw_intf = link.intf1 if link.intf1.node == swnode else link.intf2
        sw_port = swnode.ports[sw_intf]
        mapping["proxies"].append({
            "name": p.name,
            "role": "proxy",
            "ip": pnode.IP(),
            "mac": pnode.MAC(),
            "dpid": dpid_int(swnode),
            "port": int(sw_port),
        })

    out_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")

# -------- controller + REST trigger --------

def start_ryu(ryu_app: Path, ctrl_port: int, outdir: Path, mapping_path: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["MYCO_OUTDIR"] = str(outdir)
    env["MYCO_MAPPING"] = str(mapping_path)

    cmd = ["ryu-manager", str(ryu_app), "--ofp-tcp-listen-port", str(ctrl_port)]
    info("*** Starting Ryu: %s\n" % " ".join(cmd))
    proc = subprocess.Popen(cmd,
                            stdout=open(outdir / "ryu_stdout.log", "w"),
                            stderr=open(outdir / "ryu_stderr.log", "w"),
                            env=env)
    time.sleep(2.5)
    return proc

def stop_proc(proc: subprocess.Popen):
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

def rest_trigger_event(strategy: str, target_ip: str, duration_s: int, rest_port: int = 8080):
    """
    Ryu WSGI runs on 0.0.0.0:8080 by default unless configured otherwise.
    Use curl to trigger event.
    """
    body = json.dumps({"strategy": strategy, "target_ip": target_ip, "duration_s": duration_s})
    cmd = ["curl", "-sS", "-X", "POST", f"http://127.0.0.1:{rest_port}/myco/event",
           "-H", "Content-Type: application/json",
           "-d", body]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"REST trigger failed: {r.stderr.strip()}")
    return r.stdout.strip()

# -------- iperf bursts aligned to events --------

def run_udp_burst(net: Mininet, duration_s: int, kbps_per_node: int, sink_name: str, outdir: Path):
    """
    Start iperf UDP server at sink, then each other host sends UDP for duration_s.
    Returns aggregated series + PDR list.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    clients_dir = outdir / "clients"
    clients_dir.mkdir(parents=True, exist_ok=True)

    sink = net.get(sink_name)
    server_log = outdir / f"iperf_server_{sink_name}.log"
    sink.cmd("pkill -f 'iperf -s' >/dev/null 2>&1")
    sink.cmd(f"iperf -s -u -i 1 > {server_log} 2>&1 &")
    time.sleep(0.5)

    for h in net.hosts:
        if h.name == sink_name:
            continue
        log = clients_dir / f"{h.name}_to_{sink_name}.log"
        h.cmd(f"iperf -c {sink.IP()} -u -b {kbps_per_node}k -t {duration_s} -i 1 > {log} 2>&1 &")

    time.sleep(duration_s + 1.5)
    sink.cmd("pkill -f 'iperf -s' >/dev/null 2>&1")

    # parse logs
    all_series = []
    pdrs = []
    for logp in clients_dir.glob("*.log"):
        text = logp.read_text(errors="ignore")
        series, pdr = parse_iperf_client_log(text)
        if series:
            all_series.extend(series)
        if pdr is not None:
            pdrs.append(pdr)

    return all_series, pdrs

# -------- experiment runner --------

def main():
    setLogLevel("info")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ryu_app", type=str, default="ryu_myco_controller.py")
    ap.add_argument("--outdir", type=str, default="myco_experiments")
    ap.add_argument("--ctrl_port", type=int, default=6633)
    ap.add_argument("--rest_port", type=int, default=8080)
    ap.add_argument("--bw", type=int, default=10)
    ap.add_argument("--delay_ms", type=int, default=5)
    ap.add_argument("--edges", type=int, default=5)
    ap.add_argument("--kbps", type=int, default=500)
    ap.add_argument("--event_duration", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--Ns", type=str, default="50", help="Comma-separated list like 10,20,30,40,50")
    ap.add_argument("--no_cleanup", action="store_true")
    args = ap.parse_args()

    root = Path(args.outdir)
    root.mkdir(parents=True, exist_ok=True)

    Ns = [int(x.strip()) for x in args.Ns.split(",") if x.strip()]
    strategies = ["myco_scout", "myco_box", "myco_swap"]

    summary_rows = []
    mapping_path = Path("/tmp/myco_mapping.json")

    for N in Ns:
        for strategy in strategies:
            run_id = f"N{N}_{strategy}_{int(time.time())}"
            run_dir = root / run_id
            run_dir.mkdir(parents=True, exist_ok=True)

            info("\n==============================\n")
            info(f"*** RUN {run_id}\n")
            info("==============================\n")

            # start Ryu
            ryu_proc = start_ryu(Path(args.ryu_app), args.ctrl_port, run_dir / "controller", mapping_path)

            # build Mininet
            net = Mininet(controller=None, switch=OVSSwitch, link=TCLink,
                          autoSetMacs=True, autoStaticArp=True, build=False)
            net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=args.ctrl_port)

            core, edges, hosts, proxies = build_iot_topology(net, n_hosts=N, n_edges=args.edges,
                                                             bw=args.bw, delay_ms=args.delay_ms)
            net.build()
            net.start()

            # mapping json for controller strategies
            write_mapping_json(net, hosts, proxies, mapping_path)
            shutil.copy(mapping_path, run_dir / "myco_mapping.json")

            # quick reachability warm-up
            net.pingAll()

            # pick a stable sink and a stable target (avoid sink as target)
            sink = "h1"
            target = "h2" if N >= 2 else "h1"
            target_ip = net.get(target).IP()

            # run multiple synchronized rounds
            round_metrics = []
            for r in range(1, args.rounds + 1):
                info(f"*** Round {r}/{args.rounds}: trigger event + UDP burst\n")

                # trigger event first (controller installs flows, ARP steering etc.)
                rest_trigger_event(strategy, target_ip, args.event_duration, rest_port=args.rest_port)

                # traffic burst during the same event window
                series, pdrs = run_udp_burst(net, duration_s=args.event_duration,
                                             kbps_per_node=args.kbps,
                                             sink_name=sink,
                                             outdir=run_dir / "traffic" / f"round_{r}")

                thr_mean = mean(series) if series else 0.0
                thr_cov = (pstdev(series) / thr_mean) if (series and len(series) > 1 and thr_mean > 0) else 0.0
                pdr_mean = mean(pdrs) if pdrs else 0.0

                round_metrics.append((thr_mean, thr_cov, pdr_mean))

                # small cool-down for consistent next round
                time.sleep(1.0)

            # control plane latency (controller writes ctrl_latency.csv)
            lctrl = mean_ctrl_latency_ms(run_dir / "controller" / "ctrl_latency.csv")

            # aggregate across rounds
            thr_means = [x[0] for x in round_metrics]
            thr_covs = [x[1] for x in round_metrics]
            pdr_means = [x[2] for x in round_metrics]

            row = {
                "run": run_id,
                "N": N,
                "strategy": strategy,
                "throughput_mean_bps": mean(thr_means) if thr_means else 0.0,
                "throughput_cov": mean(thr_covs) if thr_covs else 0.0,
                "pdr_mean": mean(pdr_means) if pdr_means else 0.0,
                "L_ctrl_mean_ms": lctrl if lctrl is not None else 0.0,
                "rounds": args.rounds,
                "event_duration_s": args.event_duration,
                "udp_kbps_per_node": args.kbps,
                "bw_mbps": args.bw,
                "delay_ms": args.delay_ms,
                "edges": args.edges
            }
            summary_rows.append(row)

            # stop
            net.stop()
            stop_proc(ryu_proc)

            if not args.no_cleanup:
                cleanup()

    # write single comparable summary
    out_csv = root / "summary.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        cols = ["run", "N", "strategy", "throughput_mean_bps", "throughput_cov", "pdr_mean",
                "L_ctrl_mean_ms", "rounds", "event_duration_s", "udp_kbps_per_node",
                "bw_mbps", "delay_ms", "edges"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in summary_rows:
            w.writerow(r)

    print(f"Wrote: {out_csv.resolve()}")

if __name__ == "__main__":
    main()
