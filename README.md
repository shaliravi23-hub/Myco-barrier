# Myco-Barrier: Experimental Data and Environment Configurations

This repository provides the supporting data and environmental configurations for the **Myco-Barrier Framework**. The core implementation codes (SDN controller logic and strategy definitions) are provided as **Supplementary Information** files accompanying the submitted manuscript.

## 📂 Repository Structure

* **`/Environment_Configs`**: Contains scripts and configuration files for setting up the Mininet emulation environment, including the 10/30/50-node SDN-IoT topology used in the study.
* **`/Logs`**: This folder contains the raw output files generated during simulation runs and mininet, including:
    * Packet Delivery Ratio (PDR) metrics.
    * Latency and response time logs.
    * Controller resource utilization (Memory/CPU) data.
* **`orchestrate_exp.sh`**: A sample execution script providing the orchestration details for a sample run.

## 🚀 Reproduction & Verification

### Mininet Configuration
The provided configuration files allow for the reconstruction of the experimental testbed. These scripts define the network constraints and the attack vectors (TCP SYN Flood) used to evaluate the framework.

### Sample Execution
To understand the triggering mechanism of the Myco-Barrier strategies, reviewers can examine the included `.sh` files. These scripts demonstrate:
1. The initialization of the Myco-Barrier environment.
2. The execution of the 100-second simulation window.
3. The automated logging process used to obtain the data found in the `/Logs` folder.

## 📜 Legal & Usage Note
This repository is intended solely for the purpose of peer review. All rights to the Myco-Barrier architecture and implementation logic are reserved as per the primary manuscript submission.
