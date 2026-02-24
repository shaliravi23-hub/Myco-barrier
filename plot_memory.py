import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ==========================================
# DATA FROM YOUR LOGS
# ==========================================
data = {
    'Strategy': ['Myco-Scout', 'Myco-Box', 'Myco-Swap'],
    'Start_RAM': [56.50, 56.62, 56.75],
    'Peak_RAM': [57.63, 58.12, 57.88]
}

df = pd.DataFrame(data)
df['Overhead'] = df['Peak_RAM'] - df['Start_RAM']

# ==========================================
# PLOTTING LOGIC
# ==========================================
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))

# Subplot 1: Total Footprint (The "Big Picture")
colors = ['#1f77b4', '#ff7f0e', '#2ca02c'] # Blue, Orange, Green
bars1 = ax1.bar(df['Strategy'], df['Peak_RAM'], color=colors, alpha=0.8, width=0.5)

# Zoom in the Y-axis to show the small differences clearly
ax1.set_ylim(55, 59) 
ax1.set_ylabel('Peak Memory Usage (MB)', fontsize=12, fontweight='bold')
ax1.set_title('Total Memory Footprint (Lower is Better)', fontsize=14, fontweight='bold')
ax1.grid(axis='y', linestyle='--', alpha=0.3)

for bar in bars1:
    height = bar.get_height()
    ax1.annotate(f'{height:.2f} MB',
                 xy=(bar.get_x() + bar.get_width() / 2, height),
                 xytext=(0, 3), textcoords="offset points",
                 ha='center', va='bottom', fontsize=11)

# Subplot 2: Operational Overhead (The "Cost of Security")
bars2 = ax2.bar(df['Strategy'], df['Overhead'], color=colors, alpha=0.9, width=0.5)

ax2.set_ylabel('Memory Overhead (MB)', fontsize=12, fontweight='bold')
ax2.set_title('Computational Cost (Peak - Idle)', fontsize=14, fontweight='bold')
ax2.set_ylim(0, 2.0) # Scale for small values
ax2.grid(axis='y', linestyle='--', alpha=0.3)

for bar in bars2:
    height = bar.get_height()
    ax2.annotate(f'+{height:.2f} MB',
                 xy=(bar.get_x() + bar.get_width() / 2, height),
                 xytext=(0, 3), textcoords="offset points",
                 ha='center', va='bottom', fontsize=11, fontweight='bold')

plt.tight_layout()
plt.savefig('myco_memory_comparison.png', dpi=300)
print("Generated: myco_memory_comparison.png")
plt.show()
