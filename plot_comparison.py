import matplotlib.pyplot as plt
import numpy as np

# ==========================================
# DATA INPUT (From your results)
# ==========================================
strategies = ['Myco-Scout', 'Myco-Box', 'Myco-Swap']

# Data from your runs
legit_pdr = [81.25, 82.26, 84.96]  # Legitimate User Success
attack_pdr = [5.24, 11.59, 14.04]  # Attacker Success (Lower is better usually, but context matters)

# ==========================================
# PLOTTING LOGIC
# ==========================================
x = np.arange(len(strategies))  # Label locations
width = 0.35  # Width of the bars

fig, ax = plt.subplots(figsize=(10, 6))

# Create side-by-side bars
rects1 = ax.bar(x - width/2, legit_pdr, width, label='Legitimate Users (Higher is Better)', color='#2ca02c')
rects2 = ax.bar(x + width/2, attack_pdr, width, label='Attackers (Lower is Better)', color='#d62728')

# Styling
ax.set_ylabel('Packet Delivery Ratio (PDR) %', fontsize=12, fontweight='bold')
ax.set_title('Comparative Analysis of Myco-Barrier Strategies', fontsize=14, fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels(strategies, fontsize=12)
ax.set_ylim(0, 100)
ax.legend()
ax.grid(axis='y', linestyle='--', alpha=0.3)

# Function to add labels on top of bars
def autolabel(rects):
    for rect in rects:
        height = rect.get_height()
        ax.annotate(f'{height}%',
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom', fontweight='bold')

autolabel(rects1)
autolabel(rects2)

fig.tight_layout()

# Save
plt.savefig('myco_strategy_comparison.png', dpi=300)
print("Generated: myco_strategy_comparison.png")
plt.show()
