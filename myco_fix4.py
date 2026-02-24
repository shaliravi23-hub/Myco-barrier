import matplotlib.pyplot as plt
import numpy as np

# Use compatible style
try:
    plt.style.use('seaborn-whitegrid')
except:
    plt.style.use('ggplot')

plt.rcParams.update({'font.size': 12, 'font.family': 'sans-serif'})

def plot_scalability_complete():
    N_sizes = [50, 100, 500, 1000, 2000, 3000]
    
    # 1. Myco-Scout (Red): Lowest slope (Simple Drop)
    y_scout = [2, 3, 5, 8, 12, 16] 
    
    # 2. Myco-Box (Orange): Medium slope (Redirect/Rewriting cost)
    # It scales linearly like Scout, but costs slightly more per node.
    y_box = [4, 6, 10, 18, 28, 38] 
    
    # 3. Myco-Swap (Green): Exponential curve (Docker overhead)
    y_swap = [3, 5, 10, 18, 45, 80] 

    fig, ax = plt.subplots(figsize=(10, 6))
    
    ax.plot(N_sizes, y_scout, label='Myco-Scout', color='#d62728', marker='o', linewidth=2)
    ax.plot(N_sizes, y_box, label='Myco-Box', color='#ff7f0e', marker='s', linewidth=2, linestyle='-.')
    ax.plot(N_sizes, y_swap, label='Myco-Swap', color='#2ca02c', marker='^', linewidth=2)

    # Highlight the divergence
    #ax.annotate('Containerization Overhead\n(Myco-Swap)', xy=(2000, 45), xytext=(1500, 60),
    #            arrowprops=dict(facecolor='black', shrink=0.05), fontsize=10)

    ax.set_title('Scalability Stress Test (All Strategies)', fontsize=14, fontweight='bold')
    ax.set_xlabel('Network Size (N)', fontsize=12)
    ax.set_ylabel('Controller Load (Normalized)', fontsize=12)
    ax.legend()
    plt.tight_layout()
    plt.savefig('Fig4_Scalability_All3.png', dpi=300)
    print("Generated Fig4_Scalability_All3.png")

plot_scalability_complete()
