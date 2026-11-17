# Rebuttal for AGGREGATE SCORES MASK GENERALIST AGENT’S SKILL USEFULNESS
This folder contains scripts, evaluation logs, and other materials used for the rebuttal.



## Directory Structure

```
rebuttal/
├── aggregate_results_log                     # Contain the 2x2 aggregate metric and CI values for CUGA S3 and also all pruning experiments
├── cuga_raw_logs_improvement                 # Contain the CUGA raw traces and evaluation for the pruning experiments
├── paired_CI                                 # Contain the CI values logs for the paired difference
└── pruned_setting1_stateTravel_skills/       # Pruned state-travel skills for Setting 1 
    ├── cc-guided_setting1_skills/            # CC-guided skill variant
    ├── randomA_skills/                       # Random skill variant A
    ├── randomB_skills/                       # Random skill variant B
    ├── randomC_skills/                       # Random skill variant C
    └── randomD_skills/                       # Random skill variant D
└── pruned_setting3_state_skills/             # Pruned state-customer and state-shopping skills for Setting 3
    ├── cc-guided_setting3_skills/            # CC-guided skill variant
├── sampled_traces_testcases/
│   ├── sample_fuzzy_traces_cuga_opus4_6.json # 15 sampled fuzzy-matched CUGA traces with metadata
│   └── sample_fuzzy_traces_pi_opus4_6.json   # 15 sampled fuzzy-matched PI traces with metadata
├── ted_capability_subgoal_evaluation         # For TED-style capability subgoal evaluation 
├── paired_significance.py                    # script to compute paired difference CI values

```
