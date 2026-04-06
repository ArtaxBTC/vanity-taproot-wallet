#!/usr/bin/env python3
"""
vanity_wallet.py
Generates a Bitcoin Taproot P2TR (bc1p...) vanity wallet whose address starts and/or ends
with a chosen string. Uses all CPU cores via multiprocessing
(PBKDF2-HMAC-SHA512 is not GPU-friendly).

Workflow:
  1. Set TARGET_PREFIX and/or TARGET_SUFFIX below
  2. python vanity_wallet.py
  3. Write down the displayed mnemonic
  4. Shred vanity_wallet_result.json (before opening any wallet app)
  5. Import the mnemonic into your wallet

Dependency: pip install bip_utils
"""

import os
import sys
import time
import json
import signal
import multiprocessing
from pathlib import Path

# ---------------------------------------------------------------------------
#  CONFIG
# ---------------------------------------------------------------------------
TARGET_PREFIX = ["dead", "cafe"]   # list of prefixes (bc1p[prefix]...); [] = disabled
TARGET_SUFFIX = []                   # list of suffixes (bc1p...[suffix]); [] = disabled
WALLET_INDEX  = 0              # BIP86 m/86'/0'/0'/0/{index} -- 0 = first wallet
PASSPHRASE    = ""             # BIP39 passphrase (leave empty = none)
WORDS_COUNT   = 12             # 12 or 24 words (12 = 128 bits, sufficient)
WORKERS       = None           # None = os.cpu_count()
_DESKTOP            = Path.home() / "Desktop"
OUTPUT_FILE         = _DESKTOP / "vanity_wallet_result.json"
CHECKPOINT_FILE     = _DESKTOP / "vanity_wallet_checkpoint.json"
CHECKPOINT_INTERVAL = 60       # seconds between automatic checkpoint saves
# ---------------------------------------------------------------------------

BECH32M_CHARSET = set("qpzry9x8gf2tvdw0s3jn54khce6mua7l")


# ---------------------------------------------------------------------------
#  CHECKPOINT
# ---------------------------------------------------------------------------

def _load_checkpoint():
    """Load checkpoint if it matches the current target.
    Returns (prev_attempts, prev_sessions)."""
    path = Path(CHECKPOINT_FILE)
    if not path.exists():
        return 0, 0
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("target_prefix") != TARGET_PREFIX or data.get("target_suffix") != TARGET_SUFFIX:
            print(f"  [CHECKPOINT] Different target in checkpoint -- ignored."
                  f" (prefix={data.get('target_prefix')!r} suffix={data.get('target_suffix')!r})")
            return 0, 0
        if data.get("found"):
            label = _target_label()
            print(f"\n  [CHECKPOINT] Target '{label}' was already found")
            print(f"  in a previous session.")
            print(f"  Result file: {OUTPUT_FILE}")
            print(f"  Delete or rename the checkpoint file to start a new search.\n")
            sys.exit(0)
        prev = int(data.get("total_attempts", 0))
        sess = int(data.get("sessions", 0))
        return prev, sess
    except Exception as e:
        print(f"  [CHECKPOINT] Could not read checkpoint ({e}) -- starting from scratch.")
        return 0, 0


def _save_checkpoint(total_attempts, sessions, found=False):
    """Save checkpoint to disk."""
    data = {
        "target_prefix":  TARGET_PREFIX,
        "target_suffix":  TARGET_SUFFIX,
        "total_attempts": total_attempts,
        "sessions":       sessions,
        "last_saved":     time.strftime("%Y-%m-%dT%H:%M:%S"),
        "found":          found,
        "NOTE":           "Delete this file to start a new search from scratch.",
    }
    try:
        with open(CHECKPOINT_FILE, 'w', encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"\n  [WARNING] Checkpoint save failed: {e}")


# ---------------------------------------------------------------------------


def _target_label():
    """Return a human-readable description of the current target."""
    pfxs = [p for p in TARGET_PREFIX if p]
    sfxs = [s for s in TARGET_SUFFIX if s]
    p_str = "|".join(pfxs) if pfxs else ""
    s_str = "|".join(sfxs) if sfxs else ""
    if p_str and s_str:
        return f"bc1p[{p_str}]...[{s_str}]"
    if p_str:
        return f"bc1p[{p_str}]..."
    return f"bc1p...[{s_str}]"


def _worker(target_prefixes, target_suffixes, passphrase, wallet_index, words_count,
            stop_event, result_queue, counter):
    """Worker: generates random mnemonics and checks bc1p against all prefix/suffix patterns."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # workers ignore Ctrl+C
    from bip_utils import (
        Bip39MnemonicGenerator, Bip39WordsNum,
        Bip39SeedGenerator, Bip86, Bip86Coins, Bip44Changes,
        Bip84, Bip84Coins,
    )

    wn_map = {
        12: Bip39WordsNum.WORDS_NUM_12,
        15: Bip39WordsNum.WORDS_NUM_15,
        18: Bip39WordsNum.WORDS_NUM_18,
        21: Bip39WordsNum.WORDS_NUM_21,
        24: Bip39WordsNum.WORDS_NUM_24,
    }
    words_num = wn_map.get(words_count, Bip39WordsNum.WORDS_NUM_12)
    mnemonic_gen = Bip39MnemonicGenerator()

    local = 0
    while not stop_event.is_set():
        mnemonic_str = mnemonic_gen.FromWordsNumber(words_num).ToStr()
        seed         = Bip39SeedGenerator(mnemonic_str).Generate(passphrase)

        # bc1p address (BIP86 P2TR)
        bc1p = (
            Bip86.FromSeed(seed, Bip86Coins.BITCOIN)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(wallet_index)
            .PublicKey().ToAddress()
        )

        local += 1
        if local % 50 == 0:
            with counter.get_lock():
                counter.value += 50

        match = (
            (not target_prefixes or any(bc1p.startswith("bc1p" + p) for p in target_prefixes)) and
            (not target_suffixes or any(bc1p.endswith(s) for s in target_suffixes))
        )
        if match:
            matched_prefix = next((p for p in target_prefixes if bc1p.startswith("bc1p" + p)), "")
            matched_suffix = next((s for s in target_suffixes if bc1p.endswith(s)), "")
            # Also derive bc1q for reference
            bc1q = (
                Bip84.FromSeed(seed, Bip84Coins.BITCOIN)
                .Purpose().Coin().Account(0)
                .Change(Bip44Changes.CHAIN_EXT)
                .AddressIndex(wallet_index)
                .PublicKey().ToAddress()
            )
            stop_event.set()
            result_queue.put({
                "mnemonic":       mnemonic_str,
                "bc1p":           bc1p,
                "bc1q":           bc1q,
                "matched_prefix": matched_prefix,
                "matched_suffix": matched_suffix,
            })
            return


def _benchmark(passphrase, wallet_index, words_count, n=30):
    """Measure the derivation speed on one core."""
    from bip_utils import (
        Bip39MnemonicGenerator, Bip39WordsNum,
        Bip39SeedGenerator, Bip86, Bip86Coins, Bip44Changes,
    )
    wn_map = {
        12: Bip39WordsNum.WORDS_NUM_12,
        24: Bip39WordsNum.WORDS_NUM_24,
    }
    words_num    = wn_map.get(words_count, Bip39WordsNum.WORDS_NUM_12)
    mnemonic_gen = Bip39MnemonicGenerator()
    t = time.time()
    for _ in range(n):
        m    = mnemonic_gen.FromWordsNumber(words_num).ToStr()
        seed = Bip39SeedGenerator(m).Generate(passphrase)
        (
            Bip86.FromSeed(seed, Bip86Coins.BITCOIN)
            .Purpose().Coin().Account(0)
            .Change(Bip44Changes.CHAIN_EXT)
            .AddressIndex(wallet_index)
            .PublicKey().ToAddress()
        )
    return n / (time.time() - t)


def main():
    # --- Validation ---
    prefixes = [p for p in TARGET_PREFIX if p]
    suffixes = [s for s in TARGET_SUFFIX if s]
    if not prefixes and not suffixes:
        sys.exit("[ERROR] Both TARGET_PREFIX and TARGET_SUFFIX are empty.")
    invalid = [c for c in "".join(prefixes + suffixes) if c not in BECH32M_CHARSET]
    if invalid:
        sys.exit(
            f"[ERROR] Invalid bech32m characters: {''.join(sorted(set(invalid)))}\n"
            f"Allowed characters: {''.join(sorted(BECH32M_CHARSET))}\n"
            f"Excluded (visual confusion): b i o 1 and uppercase"
        )

    n_workers  = WORKERS or os.cpu_count()
    n_patterns = len(prefixes) + len(suffixes)
    p_prefix   = sum(1 / 32**len(p) for p in prefixes) if prefixes else 1.0
    p_suffix   = sum(1 / 32**len(s) for s in suffixes) if suffixes else 1.0
    expected   = int(1 / (p_prefix * p_suffix))

    # --- Load checkpoint ---
    prev_attempts, prev_sessions = _load_checkpoint()

    print(f"\n{'='*65}")
    print(f"  vanity_wallet.py -- Bitcoin bc1p vanity address generator")
    print(f"{'='*65}")
    print(f"\n  Target          : {_target_label()}")
    print(f"  Patterns        : {n_patterns}  ({len(prefixes)} prefix, {len(suffixes)} suffix)")
    print(f"  Expected tries  : {expected:,}")
    print(f"  Workers         : {n_workers} cores")
    print(f"  Mnemonic        : {WORDS_COUNT} words")
    if prev_attempts > 0:
        pct_done = prev_attempts / expected * 100
        print(f"\n  [RESUMED] Session {prev_sessions + 1}")
        print(f"  Already done    : {prev_attempts:,} attempts ({pct_done:.1f}% of expected)")
    print(f"\n  Benchmark ({30} derivations on 1 core)...")
    rate_1 = _benchmark(PASSPHRASE, WALLET_INDEX, WORDS_COUNT, 30)
    rate_n = rate_1 * n_workers
    eta_total_s = expected / rate_n
    remaining   = max(expected, expected - prev_attempts)  # at least 1 full cycle if exceeded
    remaining   = expected - prev_attempts if prev_attempts < expected else expected
    eta_rest_s  = remaining / rate_n if rate_n > 0 else 0
    print(f"  Speed           : {rate_1:.0f}/s/core  ->  {rate_n:,.0f}/s total")
    if prev_attempts == 0:
        print(f"  ETA             : ~{eta_total_s/60:.0f} min  (~{eta_total_s/3600:.1f}h)")
    elif prev_attempts < expected:
        print(f"  ETA remaining   : ~{eta_rest_s/60:.0f} min  (~{eta_rest_s/3600:.1f}h)")
        print(f"  ETA total       : ~{eta_total_s/3600:.1f}h  ({prev_attempts/rate_n/3600:.1f}h already done)")
    else:
        print(f"  ETA             : ~{eta_total_s/60:.0f} min  (past expected count, in the long tail)")
    print(f"\n  Auto checkpoint : every {CHECKPOINT_INTERVAL}s")
    print(f"  Clean stop      : Ctrl+C  (counter will be saved)")
    print(f"\n  Starting...\n")

    stop_event   = multiprocessing.Event()
    result_queue = multiprocessing.Queue()
    counter      = multiprocessing.Value('q', 0)

    procs = [
        multiprocessing.Process(
            target=_worker,
            args=(prefixes, suffixes, PASSPHRASE, WALLET_INDEX, WORDS_COUNT,
                  stop_event, result_queue, counter),
            daemon=True,
        )
        for _ in range(n_workers)
    ]

    t0        = time.time()
    last_ckpt = t0
    for p in procs:
        p.start()

    try:
        while not stop_event.is_set():
            time.sleep(5)
            now     = time.time()
            elapsed = now - t0
            count   = counter.value
            total   = prev_attempts + count
            rate    = count / elapsed if elapsed > 0 else 0
            # ETA: if we exceeded expected count, reset display to 1 full cycle
            remaining_display = (expected - total) if total < expected else expected
            eta     = remaining_display / rate / 60 if rate > 0 else 0
            pct     = total / expected * 100
            flag    = "  " if total < expected else ">>"  # '>>' = past 100%, long tail
            print(f"  {total:>12,} attempts  |  {rate:>8,.0f}/s  |  "
                  f"{flag}{pct:5.1f}%  |  ETA ~{eta:.0f} min    ", end='\r')
            # Periodic checkpoint save
            if now - last_ckpt >= CHECKPOINT_INTERVAL:
                _save_checkpoint(total, prev_sessions + 1)
                last_ckpt = now
    except KeyboardInterrupt:
        count = counter.value
        total = prev_attempts + count
        _save_checkpoint(total, prev_sessions + 1)
        elapsed = time.time() - t0
        pct = total / expected * 100
        print(f"\n\n  [STOPPED] User interrupted after {elapsed:.0f}s")
        print(f"  Total attempts  : {total:,} ({pct:.1f}% of expected)")
        print(f"  Checkpoint saved: {Path(CHECKPOINT_FILE).resolve()}")
        print(f"  Re-run the script to resume.")
        stop_event.set()
        sys.exit(0)

    for p in procs:
        p.join(timeout=3)

    elapsed = time.time() - t0
    count   = counter.value
    total   = prev_attempts + count
    result  = result_queue.get()

    # --- Save final checkpoint (found=True) ---
    _save_checkpoint(total, prev_sessions + 1, found=True)

    # --- Display result ---
    print(f"\n\n{'='*65}")
    print(f"  FOUND in {elapsed:.0f}s  ({count:,} attempts this session)")
    print(f"  Total           : {total:,} attempts over {prev_sessions + 1} session(s)")
    print(f"  Target          : {_target_label()}")
    print(f"{'='*65}")
    print(f"\n  bc1p (ordinals)  : {result['bc1p']}")
    print(f"  bc1q (payments)  : {result['bc1q']}")
    if n_patterns > 1:
        mp  = result.get('matched_prefix', '')
        ms  = result.get('matched_suffix', '')
        lbl = ("bc1p[" + mp + "]" if mp else "bc1p") + "..." + ("[" + ms + "]" if ms else "")
        print(f"  Matched pattern  : {lbl}")
    print(f"\n  Mnemonic ({WORDS_COUNT} words):")
    words = result['mnemonic'].split()
    for i, w in enumerate(words, 1):
        print(f"    {i:>2}. {w}")
    print(f"\n{'='*65}")
    print(f"  IMPORTANT:")
    print(f"  1. Write down the mnemonic above before doing anything else")
    print(f"  2. Shred {Path(OUTPUT_FILE).name} (use a file-shredding tool, not a simple delete)")
    print(f"  3. Import the mnemonic into your wallet as a new standalone seed")
    print(f"{'='*65}\n")

    # --- Temporary result save ---
    out = {
        "bc1p":           result["bc1p"],
        "bc1q":           result["bc1q"],
        "mnemonic":       result["mnemonic"],
        "matched_prefix": result.get("matched_prefix", ""),
        "matched_suffix": result.get("matched_suffix", ""),
        "wallet_index":   WALLET_INDEX,
        "words":        WORDS_COUNT,
        "attempts":     total,
        "elapsed_s":    round(elapsed, 1),
        "WARNING":      "SHRED THIS FILE (do not just delete) after importing the mnemonic into your wallet",
    }
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"  Temporary save: {Path(OUTPUT_FILE).resolve()}")


if __name__ == "__main__":
    main()
