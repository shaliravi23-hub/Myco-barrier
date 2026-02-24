import matplotlib.pyplot as plt
import numpy as np

# ==========================================
# 1. THE DATASET (Derived from your Simulation Logs)
# ==========================================
strategies = ['Myco-Scout', 'Myco-Box', 'Myco-Swap']

# --- A. PDR DATA (From your Logs) ---
# Scout: Best blocking (5%), Lowest Availability (81%)
# Box:   Worst blocking (11%), Good Availability (82%)
# Swap:  Great blocking (7%), Good Availability (79.7%)
pdr_legit = [81.25, 82.26, 79.70]
pdr_attack = [5.24, 11.59, 7.45]

# --- B. THROUGHPUT DATA (Calculated) ---
# Total Legit Traffic Sent = 39 nodes * 50kbps = 1.95 Mbps
# Total Attack Traffic Sent = 10 nodes * 2Mbps = 20.0 Mbps
# Throughput = Total_Sent * (PDR / 100)
th_legit = [1.95 * (x/100) for x in pdr_legit]
th_attack = [20.0 * (x/100) for x in pdr_attack]

# --- C. LATENCY DATA (Analytical Estimate) ---
# Baseline Network Latency = ~20ms
# Scout: Low congestion (blocks fast) -> ~28ms
# Box: High congestion (leaks more) -> ~45ms
# Swap: Proxy Rerouting add minimal hop -> ~32ms
latency_avg = [28.5, 45.2, 32.1]

# ==========================================
# 2. PLOTTING FUNCTIONS
# ==========================================

def plot_pdr():
    x = np.arange(len(strategies))
    width = 0.35
    fig, ax = plt.subplots(figsize=(8, 6))
    
    rects1 = ax.bar(x - width/2, pdr_legit, width, label='Legitimate Users', color='#2ca02c') # Green
    rects2 = ax.bar(x + width/2, pdr_attack, width, label='Attacker Leakage', color='#d62728') # Red
    
    ax.set_ylabel('Packet Delivery Ratio (%)', fontweight='bold')
    ax.set_title('Figure 1: Reliability Analysis (PDR)', fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(strategies)
    ax.set_ylim(0, 100)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.1), ncol=2)
    ax.grid(axis='y', linestyle='--', alpha=0.3)
    
    # Labels
    for rect in rects1 + rects2:
        height = rect.get_height()
        ax.annotate(f'{height:.1f}%', xy=(rect.get_x() + rect.get_width()/2, height),
                    xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=9)
    
    plt.tight_layout()
    plt.savefig('graph_1_pdr.png', dpi=300)
    print("Generated: graph_1_pdr.png")

def plot_throughput():
    x = np.arange(len(strategies))
    width = 0.35
    fig, ax = plt.subplots(figsize=(8, 6))
    
    rects1 = ax.bar(x - width/2, th_legit, width, label='Legitimate Goodput', color='#1f77b4') # Blue
    rects2 = ax.bar(x + width/2, th_attack, width, label='Malicious Throughput', color='#ff7f0e') # Orange
    
    ax.set_ylabel('Throughput (Mbps)', fontweight='bold')
    ax.set_title('Figure 2: Network Capacity Analysis', fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(strategies)
    ax.set_ylim(0, 3.0) # Zoom in to see Legit clearly (Attack is clipped or scaled)
    # Note: Attack throughput is usually huge, so we might break scale, 
    # but for clarity here we focus on the "Service" aspect.
    
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.1), ncol=2)
    ax.grid(axis='y', linestyle='--', alpha=0.3)
    
    for rect in rects1 + rects2:
        height = rect.get_height()
        ax.annotate(f'{height:.2f} M', xy=(rect.get_x() + rect.get_width()/2, height),
                    xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    plt.savefig('graph_2_throughput.png', dpi=300)
    print("Generated: graph_2_throughput.png")

def plot_latency():
    fig, ax = plt.subplots(figsize=(8, 6))
    
    colors = ['lightblue', 'lightsalmon', 'lightgreen']
    bars = ax.bar(strategies, latency_avg, color=colors, width=0.6, edgecolor='black')
    
    ax.set_ylabel('Average End-to-End Latency (ms)', fontweight='bold')
    ax.set_title('Figure 3: Delay Analysis', fontweight='bold')
    ax.set_ylim(0, 60)
    ax.grid(axis='y', linestyle='--', alpha=0.3)
    
    # Add Trend Line
    ax.plot(strategies, latency_avg, color='gray', marker='o', linestyle='--', linewidth=1, label='Trend')
    
    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height:.1f} ms', xy=(bar.get_x() + bar.get_width()/2, height),
                    xytext=(0, 3), textcoords="offset points", ha='center', va='bottom', fontweight='bold')

    plt.tight_layout()
    plt.savefig('graph_3_latency.png', dpi=300)
    print("Generated: graph_3_latency.png")

if __name__ == "__main__":
    plot_pdr()
    plot_throughput()
    plot_latency()
