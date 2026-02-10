#!/usr/bin/env python3
"""
Sandwich Attack Detector for Uniswap V2
Scans blocks from 2022-2024 and saves results to CSV with Etherscan links.

Based on the heuristics from the MEV white paper (Appendix A.1)
"""

import requests
import json
import csv
import os
import time
from datetime import datetime, timezone
from collections import defaultdict
from dotenv import load_dotenv

# Load from .env file if it exists
load_dotenv()

# Load Alchemy API key from environment variable
ALCHEMY_KEY = os.environ.get("ALCHEMY_KEY")
if not ALCHEMY_KEY:
    print("ERROR: Please set the ALCHEMY_KEY environment variable")
    print("  Option 1: Create a .env file with: ALCHEMY_KEY=your_key_here")
    print("  Option 2: export ALCHEMY_KEY=your_key_here")
    exit(1)

ALCHEMY_URL = f"https://eth-mainnet.g.alchemy.com/v2/{ALCHEMY_KEY}"

# Uniswap V2 Swap event topic
SWAP_TOPIC = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"

# Block range: 2022 to 2024
START_BLOCK = 13916166   # Jan 1, 2022
END_BLOCK = 21525419     # Dec 31, 2024

# Output files
OUTPUT_CSV = "sandwiches.csv"
PROGRESS_FILE = "progress.txt"

# Etherscan base URL
ETHERSCAN_TX = "https://etherscan.io/tx/"

def rpc_call(method, params=None, retries=3):
    """Make a JSON-RPC call to Alchemy with retry logic"""
    payload = {
        "id": 1,
        "jsonrpc": "2.0",
        "method": method,
        "params": params or []
    }
    
    for attempt in range(retries):
        try:
            response = requests.post(
                ALCHEMY_URL,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=30
            )
            result = response.json()
            if "error" in result:
                print(f"  RPC Error: {result['error']}")
                time.sleep(1)
                continue
            return result
        except Exception as e:
            print(f"  Request failed (attempt {attempt + 1}): {e}")
            time.sleep(2)
    
    return {"result": []}

def get_swap_logs(from_block, to_block):
    """Fetch all Uniswap V2 Swap events in a block range"""
    result = rpc_call("eth_getLogs", [{
        "fromBlock": hex(from_block),
        "toBlock": hex(to_block),
        "topics": [SWAP_TOPIC]
    }])
    return result.get("result", [])

def get_block_timestamp(block_num):
    """Get timestamp for a block"""
    result = rpc_call("eth_getBlockByNumber", [hex(block_num), False])
    if result.get("result"):
        return int(result["result"]["timestamp"], 16)
    return 0

def parse_swap_event(log):
    """Parse a Swap event log into structured data"""
    data = log["data"][2:]  # Remove '0x' prefix
    
    amount0In = int(data[0:64], 16)
    amount1In = int(data[64:128], 16)
    amount0Out = int(data[128:192], 16)
    amount1Out = int(data[192:256], 16)
    
    # Determine swap direction
    direction = 0 if amount0In > 0 else 1
    
    return {
        "tx_hash": log["transactionHash"],
        "tx_index": int(log["transactionIndex"], 16),
        "log_index": int(log["logIndex"], 16),
        "pair": log["address"].lower(),
        "sender": "0x" + log["topics"][1][26:].lower(),
        "to": "0x" + log["topics"][2][26:].lower(),
        "amount0In": amount0In,
        "amount1In": amount1In,
        "amount0Out": amount0Out,
        "amount1Out": amount1Out,
        "direction": direction,
        "block": int(log["blockNumber"], 16)
    }

def find_sandwiches_in_block(swaps):
    """Find sandwich attacks in a list of swaps from the same block."""
    sandwiches = []
    
    by_pair = defaultdict(list)
    for swap in swaps:
        by_pair[swap["pair"]].append(swap)
    
    for pair, pair_swaps in by_pair.items():
        if len(pair_swaps) < 3:
            continue
        
        pair_swaps.sort(key=lambda x: (x["tx_index"], x["log_index"]))
        
        for i, frontrun in enumerate(pair_swaps):
            for k in range(i + 2, len(pair_swaps)):
                backrun = pair_swaps[k]
                
                if frontrun["sender"] != backrun["sender"]:
                    continue
                
                if frontrun["direction"] == backrun["direction"]:
                    continue
                
                if frontrun["direction"] == 0:
                    frontrun_out = frontrun["amount1Out"]
                    backrun_in = backrun["amount1In"]
                    revenue_raw = backrun["amount0Out"] - frontrun["amount0In"]
                else:
                    frontrun_out = frontrun["amount0Out"]
                    backrun_in = backrun["amount0In"]
                    revenue_raw = backrun["amount1Out"] - frontrun["amount1In"]
                
                if backrun_in == 0 or abs(frontrun_out - backrun_in) / backrun_in > 0.001:
                    continue
                
                victims = []
                for j in range(i + 1, k):
                    victim = pair_swaps[j]
                    if victim["direction"] == frontrun["direction"]:
                        if victim["tx_hash"] != frontrun["tx_hash"] and victim["tx_hash"] != backrun["tx_hash"]:
                            victims.append(victim)
                
                if victims:
                    sandwiches.append({
                        "block": frontrun["block"],
                        "pair": pair,
                        "attacker": frontrun["sender"],
                        "frontrun_tx": frontrun["tx_hash"],
                        "backrun_tx": backrun["tx_hash"],
                        "victim_txs": [v["tx_hash"] for v in victims],
                        "num_victims": len(victims),
                        "revenue_raw": revenue_raw,
                    })
    
    return sandwiches

def init_csv():
    """Initialize CSV file with headers if it doesn't exist"""
    if not os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'frontrun_etherscan',
                'victim_etherscan', 
                'backrun_etherscan',
                'block_number',
                'timestamp',
                'datetime_utc',
                'pair_address',
                'attacker_address',
                'frontrun_tx',
                'victim_tx',
                'backrun_tx',
                'num_victims',
                'revenue_eth',
                'revenue_raw'
            ])
        print(f"Created {OUTPUT_CSV}")

def append_to_csv(sandwiches, block_timestamps):
    """Append sandwich records to CSV"""
    with open(OUTPUT_CSV, 'a', newline='') as f:
        writer = csv.writer(f)
        for s in sandwiches:
            ts = block_timestamps.get(s["block"], 0)
            dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if ts else ""
            
            # Write one row per victim
            for victim_tx in s["victim_txs"]:
                # Convert revenue from wei to ETH (divide by 10^18)
                revenue_eth = s["revenue_raw"] / 1e18
                writer.writerow([
                    f'{ETHERSCAN_TX}{s["frontrun_tx"]}',
                    f'{ETHERSCAN_TX}{victim_tx}',
                    f'{ETHERSCAN_TX}{s["backrun_tx"]}',
                    s["block"],
                    ts,
                    dt_str,
                    s["pair"],
                    s["attacker"],
                    s["frontrun_tx"],
                    victim_tx,
                    s["backrun_tx"],
                    s["num_victims"],
                    f"{revenue_eth:.6f}",
                    s["revenue_raw"]
                ])

def save_progress(block_num):
    """Save current progress to file"""
    with open(PROGRESS_FILE, 'w') as f:
        f.write(str(block_num))

def load_progress():
    """Load progress from file, or return START_BLOCK"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return int(f.read().strip())
    return START_BLOCK

def main():
    print("=" * 70)
    print("🥪 Sandwich Attack Detector - 2022 to 2024")
    print("=" * 70)
    
    # Initialize
    init_csv()
    current_block = load_progress()
    
    total_blocks = END_BLOCK - START_BLOCK
    blocks_done = current_block - START_BLOCK
    
    print(f"\nBlock range: {START_BLOCK:,} to {END_BLOCK:,}")
    print(f"Total blocks: {total_blocks:,}")
    print(f"Starting from block: {current_block:,}")
    print(f"Blocks remaining: {END_BLOCK - current_block:,}")
    print(f"Output file: {OUTPUT_CSV}")
    print(f"\nPress Ctrl+C to stop (progress will be saved)\n")
    
    # NOTE: Free-tier Alchemy only allows eth_getLogs over a 10-block range.
    # If you upgrade your plan, you can safely increase this to speed up scanning.
    BATCH_SIZE = 10  # Blocks per batch (must be <= 10 on free tier)
    total_sandwiches = 0
    start_time = time.time()
    
    try:
        while current_block < END_BLOCK:
            from_block = current_block
            to_block = min(current_block + BATCH_SIZE - 1, END_BLOCK)
            
            # Progress indicator
            blocks_done = from_block - START_BLOCK
            progress_pct = (blocks_done / total_blocks) * 100
            elapsed = time.time() - start_time
            
            if blocks_done > 0 and elapsed > 0:
                blocks_per_sec = blocks_done / elapsed
                remaining_blocks = END_BLOCK - from_block
                eta_seconds = remaining_blocks / blocks_per_sec if blocks_per_sec > 0 else 0
                eta_hours = eta_seconds / 3600
                eta_str = f"ETA: {eta_hours:.1f}h"
            else:
                eta_str = "ETA: calculating..."
            
            print(f"\r[{progress_pct:5.2f}%] Block {from_block:,} | {eta_str} | Sandwiches: {total_sandwiches:,}", end="    ", flush=True)
            
            # Get all swap events in this batch
            logs = get_swap_logs(from_block, to_block)
            
            if logs:
                swaps = [parse_swap_event(log) for log in logs]
                
                # Group by block
                by_block = defaultdict(list)
                for swap in swaps:
                    by_block[swap["block"]].append(swap)
                
                # Get timestamps for blocks with sandwiches
                block_timestamps = {}
                
                batch_sandwiches = []
                for block_num, block_swaps in by_block.items():
                    sandwiches = find_sandwiches_in_block(block_swaps)
                    if sandwiches:
                        if block_num not in block_timestamps:
                            block_timestamps[block_num] = get_block_timestamp(block_num)
                        batch_sandwiches.extend(sandwiches)
                
                if batch_sandwiches:
                    append_to_csv(batch_sandwiches, block_timestamps)
                    total_sandwiches += len(batch_sandwiches)
            
            current_block = to_block + 1
            save_progress(current_block)
            
    except KeyboardInterrupt:
        print(f"\n\n{'=' * 70}")
        print(f"⏸️  Stopped by user. Progress saved at block {current_block:,}")
        print(f"Total sandwiches found: {total_sandwiches:,}")
        print(f"Results saved to: {OUTPUT_CSV}")
        print(f"Run again to resume from where you left off.")
        print(f"{'=' * 70}")
        return
    
    # Completed!
    elapsed = time.time() - start_time
    print(f"\n\n{'=' * 70}")
    print(f"✅ COMPLETED! Scanned all blocks from 2022 to 2024")
    print(f"Total sandwiches found: {total_sandwiches:,}")
    print(f"Time elapsed: {elapsed/3600:.1f} hours")
    print(f"Results saved to: {OUTPUT_CSV}")
    print(f"{'=' * 70}")

if __name__ == "__main__":
    main()
