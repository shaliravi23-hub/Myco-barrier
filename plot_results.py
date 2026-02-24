import matplotlib.pyplot as plt
import pandas as pd
import io

# ==========================================
# DATA SECTION
# ==========================================

# 1. RESOURCE LOGS
log_data = """
Time,CPU,RAM
2.05,0.0,56.51
15.34,8.0,57.14
17.35,50.9,57.51
19.35,2.5,57.51
21.35,24.0,57.51
23.36,17.5,57.76
25.36,6.0,57.76
27.36,8.5,57.76
29.36,16.0,57.76
31.37,10.5,57.76
33.37,29.0,57.76
35.37,1.5,57.76
37.37,0.5,57.76
42.41,3.0,57.76
48.41,1.5,57.76
60.44,0.0,57.76
"""

# 2. PDR RESULTS
pdr_data = {
    'Category': ['Legitimate Users', 'IoT Botnet'],
    'PDR': [69.07, 8.05]
}

# ==========================================
# PLOTTING LOGIC
# ==========================================

def plot_resources():
    # Parse the text data
    df = pd.read_csv(io.StringIO(log_data))
    
    # --- THE FIX IS HERE ---
    # Convert columns to raw numpy arrays to prevent version conflicts
    time_val = df['Time'].to_numpy()
    cpu_val = df['CPU'].to_numpy()
    ram_val = df['RAM'].to_numpy()
    # -----------------------

    fig, ax1 = plt.subplots(figsize=(10, 6))

    # Plot CPU on Left Y-Axis
    color = 'tab:red'
    ax1.set_xlabel('Simulation Time (s)', fontsize=12)
    ax1.set_ylabel('CPU Usage (%)', color=color, fontsize=12)
    ax1.plot(time_val, cpu_val, color=color, marker='o', linestyle='-', label='CPU Load')
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.set_ylim(-5, 60) # Scale for CPU
    ax1.grid(True, alpha=0.3)

    # Plot RAM on Right Y-Axis
    ax2 = ax1.twinx()
    color = 'tab:blue'
    ax2.set_ylabel('RAM Usage (MB)', color=color, fontsize=12)
    ax2.plot(time_val, ram_val, color=color, marker='s', linestyle='--', label='Memory Footprint')
    ax2.tick_params(axis='y', labelcolor=color)
    ax2.set_ylim(50, 70) # Scale for RAM

    # Annotations
    plt.title('Myco-Barrier Resource Consumption Analysis', fontsize=14, fontweight='bold')
    
    # Annotate the Attack Spike
    ax1.annotate('Attack Detected\n(Logic Triggered)', xy=(17.35, 50.9), xytext=(20, 55),
                 arrowprops=dict(facecolor='black', shrink=0.05))
    
    # Annotate Stability
    ax2.annotate('System Stabilized\n(+1.2MB overhead)', xy=(60.44, 57.76), xytext=(40, 65),
                 arrowprops=dict(facecolor='blue', shrink=0.05))

    fig.tight_layout()
    plt.savefig('myco_resource_usage.png', dpi=300)
    print("Generated: myco_resource_usage.png")

def plot_pdr():
    fig, ax = plt.subplots(figsize=(8, 6))
    
    colors = ['#2ca02c', '#d62728'] # Green for Good, Red for Bad
    bars = ax.bar(pdr_data['Category'], pdr_data['PDR'], color=colors, width=0.5)
    
    # Add value labels on top
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.2f}%',
                ha='center', va='bottom', fontsize=12, fontweight='bold')

    ax.set_ylabel('Packet Delivery Ratio (PDR) %', fontsize=12)
    ax.set_title('Effectiveness of Myco-Barrier Defense', fontsize=14, fontweight='bold')
    ax.set_ylim(0, 100)
    ax.grid(axis='y', linestyle='--', alpha=0.5)
    
    plt.savefig('myco_pdr_effectiveness.png', dpi=300)
    print("Generated: myco_pdr_effectiveness.png")

if __name__ == "__main__":
    plot_resources()
    plot_pdr()
