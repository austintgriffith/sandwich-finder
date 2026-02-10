# Ethereum Sandwich Attack Detector

A script made for Agostino to scan Ethereum blocks from 2022-2024 for Uniswap V2 sandwich attacks and output results to CSV with Etherscan links.

Based on the heuristics from the white paper:

**[Maximal Extractable Value and Allocative Inefficiencies in Public Blockchains](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3997796)**  
_Agostino Capponi, Ruizhe Jia, Kanye Ye Wang_

## Setup (one time)

```bash
cd /Users/austingriffith/Desktop/txndata
python3 -m venv venv
source venv/bin/activate
pip install requests python-dotenv
```

## Configure API Key

Create a `.env` file with your Alchemy API key:

```bash
echo "ALCHEMY_KEY=your_alchemy_api_key_here" > .env
```

This file is gitignored and won't be committed.

## Run the Scanner

```bash
cd /Users/austingriffith/Desktop/txndata
source venv/bin/activate
python3 find_sandwiches.py
```

The script will:

- Scan blocks 13,916,166 to 21,525,419 (Jan 1, 2022 → Dec 31, 2024)
- Save results to `sandwiches.csv` with Etherscan links
- Save progress to `progress.txt` so you can stop/resume anytime
- Show ETA and progress percentage

Press `Ctrl+C` to stop. Run again to resume from where you left off.

## Output

Results are saved to `sandwiches.csv` with these columns:

| Column               | Description                            |
| -------------------- | -------------------------------------- |
| `frontrun_etherscan` | Link to frontrun tx on Etherscan       |
| `victim_etherscan`   | Link to victim tx on Etherscan         |
| `backrun_etherscan`  | Link to backrun tx on Etherscan        |
| `block_number`       | Block where attack occurred            |
| `timestamp`          | Unix timestamp                         |
| `datetime_utc`       | Human readable date/time               |
| `pair_address`       | Uniswap V2 pair contract               |
| `attacker_address`   | MEV bot address                        |
| `frontrun_tx`        | Frontrun transaction hash              |
| `victim_tx`          | Victim transaction hash                |
| `backrun_tx`         | Backrun transaction hash               |
| `num_victims`        | Number of victims in this sandwich     |
| `revenue_eth`        | Attacker profit in ETH                 |
| `revenue_raw`        | Attacker profit in wei (for precision) |

## Reset Progress

To start over from the beginning:

```bash
rm -f progress.txt sandwiches.csv
```

## Check Progress

```bash
cat progress.txt
wc -l sandwiches.csv
```

## How Detection Works

A sandwich attack is identified when:

1. **TA1 (frontrun)** and **TA2 (backrun)** are in the same block
2. Both swap in the **same Uniswap V2 pair** but in **opposite directions**
3. TA2's input amount equals TA1's output amount (position closure)
4. **TV (victim)** executes between them, same direction as TA1
5. Same sender address for TA1 and TA2 (the attacker)

```
Block N:
  [tx i] TA1 - Attacker buys token (frontrun)
  [tx j] TV  - Victim buys token (gets worse price)
  [tx k] TA2 - Attacker sells token (backrun, profits)
```

## Successfull Run
```
======================================================================
🥪 Sandwich Attack Detector - 2022 to 2024
======================================================================

Block range: 13,916,166 to 21,525,419
Total blocks: 7,609,253
Starting from block: 13,941,166
Blocks remaining: 7,584,253
Output file: sandwiches.csv

Press Ctrl+C to stop (progress will be saved)

[ 0.34%] Block 13,941,826 | ETA: 23.4h | Sandwiches: 75      Request failed (attempt 1): ('Connection aborted.', ConnectionResetError(54, 'Connection reset by peer'))
[ 0.38%] Block 13,944,836 | ETA: 96.1h | Sandwiches: 531    
```
